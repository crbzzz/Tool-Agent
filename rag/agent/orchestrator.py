"""Mistral Agents orchestration loop with tool calling."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rag.agent.mistral_client import (
    MistralAgentsClient,
    extract_assistant_message,
    extract_assistant_message_dict,
)
from rag.agent.policy import build_policy_message
from rag.agent.tool_registry import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 3


@dataclass
class OrchestratorResult:
    final_answer: str
    tool_trace: List[Dict[str, Any]]


class AgentOrchestrator:
    """Runs a chat turn against a pre-configured Mistral Agent and executes tool calls."""

    def __init__(
        self,
        mistral_client: MistralAgentsClient,
        agent_id: str,
        registry: Optional[ToolRegistry] = None,
        max_tool_steps: int = MAX_TOOL_STEPS,
    ) -> None:
        self.client = mistral_client
        self.agent_id = agent_id
        self.registry = registry or build_default_registry()
        self.max_tool_steps = max_tool_steps

    def run(self, user_message: str) -> OrchestratorResult:
        """Run the orchestration loop for one user message (stateless)."""

        messages: List[Dict[str, Any]] = [build_policy_message(), {"role": "user", "content": user_message}]
        result, _updated = self.run_with_messages(messages)
        return result

    def run_with_messages(self, messages: List[Dict[str, Any]]) -> tuple[OrchestratorResult, List[Dict[str, Any]]]:
        """Run the orchestration loop using an existing message list.

        Returns (result, updated_messages).
        """

        tool_trace: List[Dict[str, Any]] = []

        if not messages:
            messages = [build_policy_message()]

        # Ensure policy is present once at the beginning.
        if messages[0].get("role") != "system":
            messages = [build_policy_message(), *messages]

        last_content: str = ""

        def _run_tools(tool_calls: Any) -> None:
            for call in tool_calls:
                name = call.name
                arguments = call.arguments if isinstance(call.arguments, dict) else {"_raw": call.arguments}
                logger.info("Tool call: %s args=%s", name, arguments)
                start = time.perf_counter()
                try:
                    handler = self.registry.get(name)
                    if handler is None:
                        result = {"ok": False, "data": None, "error": f"Unknown tool: {name}"}
                    else:
                        result = handler(arguments)
                        if not isinstance(result, dict) or "ok" not in result:
                            result = {"ok": False, "data": None, "error": f"Invalid tool result from {name}"}
                except Exception as exc:
                    logger.exception("Tool handler failed: %s", name)
                    result = {"ok": False, "data": None, "error": f"Tool {name} raised: {exc}"}

                elapsed_ms = int((time.perf_counter() - start) * 1000)
                if isinstance(result, dict) and "timings_ms" not in result:
                    result["timings_ms"] = elapsed_ms

                tool_trace.append(
                    {
                        "name": name,
                        "arguments": arguments,
                        "ok": bool(result.get("ok")),
                        "error": result.get("error"),
                    }
                )

                tool_content = json.dumps(result, ensure_ascii=False)
                tool_msg: Dict[str, Any] = {"role": "tool", "name": name, "content": tool_content}
                if getattr(call, "call_id", None):
                    tool_msg["tool_call_id"] = call.call_id
                messages.append(tool_msg)

        # Allow up to N tool-execution rounds.
        for step in range(self.max_tool_steps):
            logger.info("Agent completion step=%s", step)
            response = self.client.complete_with_role_fallback(agent_id=self.agent_id, messages=messages)
            assistant_msg = extract_assistant_message_dict(response)
            content, tool_calls = extract_assistant_message(response)
            last_content = content or last_content

            if not tool_calls:
                # Preserve assistant response in the session history.
                messages.append(assistant_msg)
                return OrchestratorResult(final_answer=content, tool_trace=tool_trace), messages

            # Important: maintain correct message order: user -> assistant -> tool -> assistant...
            # The assistant message that contained the tool_calls must be present before tool outputs.
            messages.append(assistant_msg)

            _run_tools(tool_calls)

        # After tool rounds are exhausted, do one final completion to produce an answer.
        try:
            logger.info("Agent final completion after tool rounds")
            response = self.client.complete_with_role_fallback(agent_id=self.agent_id, messages=messages)
            content, tool_calls = extract_assistant_message(response)
            if tool_calls:
                logger.warning("Agent requested tools after max_tool_steps; returning best-effort answer")
            # Append the final assistant message for session continuity.
            messages.append({"role": "assistant", "content": str(content or "")})
            return OrchestratorResult(final_answer=content or last_content or "", tool_trace=tool_trace), messages
        except Exception:
            fallback = last_content.strip() or "I couldn't complete the task within the tool step limit."
            return OrchestratorResult(final_answer=fallback, tool_trace=tool_trace), messages
