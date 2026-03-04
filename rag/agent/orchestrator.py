"""Mistral Agents orchestration loop with tool calling."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rag.agent.mistral_client import (
    MistralAgentsClient,
    NormalizedToolCall,
    extract_assistant_message,
    extract_assistant_message_dict,
)
from rag.agent.response_contract import (
    ModelOutputValidationError,
    normalized_response_to_markdown,
    parse_final_response_from_text,
    parse_tool_calls_from_text,
)
from rag.agent.policy import build_policy_message
from rag.agent.tool_registry import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)

MAX_TOOL_STEPS = 3

# Heuristics to avoid exceeding model context limits.
# We approximate token usage by character count and keep a safe buffer.
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "200000"))
MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "20000"))
MAX_TOOL_LIST_ITEMS = int(os.getenv("MAX_TOOL_LIST_ITEMS", "200"))
MAX_TOOL_TEXT_CHARS = int(os.getenv("MAX_TOOL_TEXT_CHARS", "8000"))


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

        def _sanitize_messages(msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            """Best-effort sanitizer for message history sent to Mistral.

            This prevents invalid requests such as:
            - assistant message with both content and tool_calls missing/None
            - tool message missing content/name
            - None values that the API may treat as missing
            """

            cleaned: List[Dict[str, Any]] = []
            for m in msgs or []:
                if not isinstance(m, dict):
                    continue
                role = m.get("role")
                if role not in {"system", "user", "assistant", "tool"}:
                    continue

                mm: Dict[str, Any] = {k: v for k, v in m.items() if v is not None}

                # Ensure content is always a string for system/user/assistant/tool.
                if role in {"system", "user", "assistant", "tool"}:
                    content = mm.get("content", "")
                    if content is None:
                        content = ""
                    if not isinstance(content, str):
                        content = str(content)
                    mm["content"] = content

                if role == "assistant":
                    # Drop tool_calls if it's None; keep if it exists and is non-empty.
                    if mm.get("tool_calls") is None:
                        mm.pop("tool_calls", None)
                    # If assistant has neither content nor tool_calls, drop it.
                    if not mm.get("content") and not mm.get("tool_calls"):
                        continue

                if role == "tool":
                    # Tool messages must include a tool name.
                    name = mm.get("name")
                    if not isinstance(name, str) or not name.strip():
                        continue
                    mm["name"] = name
                    # tool_call_id must not be None
                    if mm.get("tool_call_id") is None:
                        mm.pop("tool_call_id", None)

                cleaned.append(mm)

            return cleaned

        def _trim_history_by_chars(msgs: List[Dict[str, Any]], max_chars: int) -> List[Dict[str, Any]]:
            if max_chars <= 0:
                return msgs
            if not msgs:
                return msgs

            system_msg: Optional[Dict[str, Any]] = None
            rest = msgs
            if msgs and msgs[0].get("role") == "system":
                system_msg = msgs[0]
                rest = msgs[1:]

            kept: List[Dict[str, Any]] = []
            total = 0

            # Keep newest messages first, then reverse to preserve order.
            for m in reversed(rest):
                content = m.get("content")
                size = len(content) if isinstance(content, str) else len(str(content))
                if kept and total + size > max_chars:
                    break
                kept.append(m)
                total += size

            kept.reverse()
            if system_msg is not None:
                return [system_msg, *kept]
            return kept

        def _shrink_tool_result(result: Dict[str, Any]) -> Dict[str, Any]:
            """Shrink potentially huge tool results to keep prompts manageable."""

            try:
                out = dict(result)
                data = out.get("data")
                if isinstance(data, dict):
                    # Common patterns: directory listings and search results.
                    for list_key in ("items", "results"):
                        lst = data.get(list_key)
                        if isinstance(lst, list) and len(lst) > MAX_TOOL_LIST_ITEMS:
                            data[list_key] = lst[:MAX_TOOL_LIST_ITEMS]
                            data["truncated"] = True
                            data["truncated_reason"] = f"{list_key} limited to {MAX_TOOL_LIST_ITEMS}"
                    # Large text fields
                    for text_key in ("content", "text", "body"):
                        txt = data.get(text_key)
                        if isinstance(txt, str) and len(txt) > MAX_TOOL_TEXT_CHARS:
                            data[text_key] = txt[:MAX_TOOL_TEXT_CHARS]
                            data["truncated"] = True
                            data["truncated_reason"] = f"{text_key} limited to {MAX_TOOL_TEXT_CHARS} chars"
                    out["data"] = data

                tool_content = json.dumps(out, ensure_ascii=False)
                if len(tool_content) <= MAX_TOOL_RESULT_CHARS:
                    return out

                # If still too large, fall back to a minimal preview.
                preview = tool_content[:MAX_TOOL_RESULT_CHARS]
                return {
                    "ok": bool(result.get("ok")),
                    "data": {
                        "truncated": True,
                        "truncated_reason": f"tool result limited to {MAX_TOOL_RESULT_CHARS} chars",
                        "preview": preview,
                    },
                    "error": result.get("error"),
                }
            except Exception:
                return {
                    "ok": False,
                    "data": {"truncated": True, "truncated_reason": "tool result shrink failed"},
                    "error": "Tool result too large",
                }

        if not messages:
            messages = [build_policy_message()]

        # Sanitize any existing history (older sessions may contain None fields).
        messages = _sanitize_messages(messages)

        # Ensure policy is present once at the beginning.
        if not messages or messages[0].get("role") != "system":
            messages = [build_policy_message(), *messages]

        # Final sanitation after forcing policy.
        messages = _sanitize_messages(messages)

        # Prevent oversized prompts by trimming old history.
        messages = _trim_history_by_chars(messages, MAX_HISTORY_CHARS)

        last_content: str = ""

        def _tool_calls_from_content(content: str) -> List[NormalizedToolCall]:
            """Fallback: parse tool calls embedded as JSON inside assistant content."""

            if not isinstance(content, str) or not content.strip():
                return []
            return parse_tool_calls_from_text(content)

        def _best_effort_final_answer(content: str) -> str:
            """Convert contract-style JSON final responses to a legacy markdown string.

            If content is not JSON, returns it unchanged.
            If content is JSON but violates the contract, returns it unchanged.
            """

            if not isinstance(content, str):
                return str(content)
            if not content.strip():
                return ""
            try:
                parsed = parse_final_response_from_text(content)
                if parsed is None:
                    return content
                return normalized_response_to_markdown(parsed)
            except ModelOutputValidationError:
                return content

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

                # Shrink tool outputs before adding them to message history.
                if isinstance(result, dict):
                    result = _shrink_tool_result(result)

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

            # Fallback: if the SDK didn't surface tool_calls, attempt to parse tool calls from content.
            if not tool_calls:
                embedded = _tool_calls_from_content(content)
                if embedded:
                    tool_calls = embedded

            if not tool_calls:
                # Preserve assistant response in the session history.
                messages.append(assistant_msg)
                return OrchestratorResult(final_answer=_best_effort_final_answer(content), tool_trace=tool_trace), messages

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
            rendered = _best_effort_final_answer(str(content or ""))
            messages.append({"role": "assistant", "content": str(content or "")})
            return OrchestratorResult(final_answer=rendered or last_content or "", tool_trace=tool_trace), messages
        except Exception:
            fallback = last_content.strip() or "I couldn't complete the task within the tool step limit."
            return OrchestratorResult(final_answer=fallback, tool_trace=tool_trace), messages
