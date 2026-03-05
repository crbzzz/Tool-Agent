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
    ModelOutputParseError,
    ModelOutputValidationError,
    extract_first_json_object,
    normalized_response_to_markdown,
    parse_final_response_from_text,
    parse_tool_calls_from_text,
)
from rag.agent.policy import build_policy_message
from rag.agent.tool_registry import ToolRegistry, build_default_registry
from rag.state.runs import (
    ToolTraceEntry,
    append_tool_trace,
    finish_run,
    redact_args_summary,
    redact_text,
    start_run,
    infer_affected_items_count,
)

logger = logging.getLogger(__name__)

def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        v = int(str(raw).strip())
    except Exception:
        return default
    if v < min_value:
        return min_value
    if v > max_value:
        return max_value
    return v


MAX_TOOL_STEPS = _env_int("MAX_TOOL_STEPS", 3, min_value=1, max_value=20)

# Heuristics to avoid exceeding model context limits.
# We approximate token usage by character count and keep a safe buffer.
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "200000"))
MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "20000"))
MAX_TOOL_LIST_ITEMS = int(os.getenv("MAX_TOOL_LIST_ITEMS", "200"))
MAX_TOOL_TEXT_CHARS = int(os.getenv("MAX_TOOL_TEXT_CHARS", "8000"))


@dataclass
class OrchestratorResult:
    run_id: str
    final_answer: str
    normalized_response: Dict[str, Any]
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

    def run(self, user_message: str, *, user_id: str = "default") -> OrchestratorResult:
        """Run the orchestration loop for one user message (stateless)."""

        messages: List[Dict[str, Any]] = [build_policy_message(), {"role": "user", "content": user_message}]
        result, _updated = self.run_with_messages(messages, user_id=user_id)
        return result

    def run_with_messages(
        self, messages: List[Dict[str, Any]], *, user_id: str = "default"
    ) -> tuple[OrchestratorResult, List[Dict[str, Any]]]:
        """Run the orchestration loop using an existing message list.

        Returns (result, updated_messages).
        """

        tool_trace: List[Dict[str, Any]] = []
        step_index = 0

        def _latest_user_summary(msgs: List[Dict[str, Any]]) -> str:
            for m in reversed(msgs or []):
                if isinstance(m, dict) and m.get("role") == "user":
                    c = m.get("content")
                    s = c if isinstance(c, str) else str(c)
                    return (s or "").strip()[:200]
            return ""

        run_id = start_run(user_id=(user_id or "default"), input_summary=_latest_user_summary(messages))
        run_finished = False

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
                    # tool_call_id is required for tool-calling APIs.
                    tci = mm.get("tool_call_id")
                    if not isinstance(tci, str) or not tci.strip():
                        continue
                    mm["tool_call_id"] = tci

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

        def _normalized_response_or_fallback(content: str) -> Dict[str, Any]:
            try:
                parsed = parse_final_response_from_text(content)
                if parsed is None:
                    raise ModelOutputParseError("no normalized response")
                # Dataclass -> dict
                return {
                    "type": parsed.type,
                    "answer": parsed.answer,
                    "blocks": [
                        {
                            "type": b.type,
                            "content": b.content,
                            "language": b.language,
                            "filename": b.filename,
                        }
                        for b in (parsed.blocks or [])
                    ],
                    "sources": parsed.sources or [],
                    "grounded": bool(parsed.grounded),
                    "next_step": parsed.next_step or "",
                }
            except Exception:
                text = (content or "").strip()
                return {
                    "type": "text",
                    "answer": text,
                    "blocks": [{"type": "text", "content": text, "language": "", "filename": ""}] if text else [],
                    "sources": [],
                    "grounded": None,
                    "next_step": "",
                }

        def _non_empty_answer(candidate: str) -> str:
            text = (candidate or "").strip()
            if text:
                return text
            # Best-effort hint from tools
            last_err = None
            for t in reversed(tool_trace):
                err = t.get("error")
                if err:
                    last_err = str(err)
                    break
            if last_err:
                return f"I couldn't complete the request. Last tool error: {last_err}"
            return "I couldn't generate a response. Please try again."

        def _run_tools(tool_calls: Any) -> None:
            nonlocal step_index
            for call in tool_calls:
                name = call.name
                arguments = call.arguments if isinstance(call.arguments, dict) else {"_raw": call.arguments}

                # Robust argument normalization:
                # - If arguments arrive as a raw string, attempt to parse JSON.
                # - If arguments contain nested {"_raw": ...} values, unwrap them.
                if isinstance(arguments, dict):
                    # Unwrap nested {"_raw": ...} for common fields like path/root.
                    for k, v in list(arguments.items()):
                        if isinstance(v, dict) and set(v.keys()) == {"_raw"}:
                            arguments[k] = v.get("_raw")

                    # If the whole args payload is a single _raw string, parse it.
                    if set(arguments.keys()) == {"_raw"} and isinstance(arguments.get("_raw"), str):
                        raw = (arguments.get("_raw") or "").strip()
                        if raw:
                            parsed: Optional[Dict[str, Any]] = None
                            try:
                                obj = json.loads(raw)
                                if isinstance(obj, dict):
                                    parsed = obj
                            except Exception:
                                try:
                                    obj = extract_first_json_object(raw)
                                    if isinstance(obj, dict):
                                        parsed = obj
                                except ModelOutputParseError:
                                    parsed = None

                            if parsed is not None:
                                arguments = parsed
                logger.info("Tool call: %s args=%s", name, arguments)
                started_at_iso = _now_iso()
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
                finished_at_iso = _now_iso()
                if isinstance(result, dict) and "timings_ms" not in result:
                    result["timings_ms"] = elapsed_ms

                # Shrink tool outputs before adding them to message history.
                if isinstance(result, dict):
                    result = _shrink_tool_result(result)

                ok = bool(result.get("ok")) if isinstance(result, dict) else False
                err = None
                if isinstance(result, dict) and result.get("error"):
                    err = redact_text(str(result.get("error")), max_len=1200)

                args_summary = redact_args_summary(name, arguments)
                affected = infer_affected_items_count(result)

                try:
                    append_tool_trace(
                        run_id,
                        ToolTraceEntry(
                            step_index=step_index,
                            tool_name=name,
                            args_summary=args_summary,
                            started_at_iso=started_at_iso,
                            finished_at_iso=finished_at_iso,
                            duration_ms=elapsed_ms,
                            ok=ok,
                            error=err,
                            affected_items_count=affected,
                        ),
                    )
                except Exception:
                    logger.exception("Failed to append tool trace")

                tool_trace.append(
                    {
                        "step_index": step_index,
                        "tool_name": name,
                        "args_summary": args_summary,
                        "started_at_iso": started_at_iso,
                        "finished_at_iso": finished_at_iso,
                        "duration_ms": elapsed_ms,
                        "ok": ok,
                        "error": err,
                        "affected_items_count": affected,
                    }
                )

                step_index += 1

                tool_content = json.dumps(result, ensure_ascii=False)
                tool_msg: Dict[str, Any] = {"role": "tool", "name": name, "content": tool_content}
                if getattr(call, "call_id", None):
                    tool_msg["tool_call_id"] = call.call_id
                messages.append(tool_msg)

        # Allow up to N tool-execution rounds.
        try:
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
                    rendered = _best_effort_final_answer(content)
                    normalized = _normalized_response_or_fallback(str(content or rendered or ""))
                    try:
                        finish_run(
                            run_id,
                            status="success",
                            error_message=None,
                            output_type=str(normalized.get("type") or "text"),
                            grounded=normalized.get("grounded"),
                        )
                        run_finished = True
                    except Exception:
                        logger.exception("Failed to finish run")
                    return (
                        OrchestratorResult(
                            run_id=run_id,
                            final_answer=_non_empty_answer(rendered),
                            normalized_response=normalized,
                            tool_trace=tool_trace,
                        ),
                        messages,
                    )

                # Important: maintain correct message order: user -> assistant -> tool -> assistant...
                # The assistant message that contained the tool_calls must be present before tool outputs.
                messages.append(assistant_msg)

                _run_tools(tool_calls)
        except Exception as exc:
            logger.exception("Orchestration failed")
            safe_err = redact_text(str(exc), max_len=1200)
            try:
                finish_run(
                    run_id,
                    status="error",
                    error_message=safe_err,
                    output_type="text",
                    grounded=None,
                )
                run_finished = True
            except Exception:
                logger.exception("Failed to finish error run")
            fallback = "I couldn't complete the request. Please try again."
            return (
                OrchestratorResult(
                    run_id=run_id,
                    final_answer=fallback,
                    normalized_response={
                        "type": "text",
                        "answer": fallback,
                        "blocks": [{"type": "text", "content": fallback, "language": "", "filename": ""}],
                        "sources": [],
                        "grounded": None,
                        "next_step": "",
                    },
                    tool_trace=tool_trace,
                ),
                messages,
            )

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
            normalized = _normalized_response_or_fallback(str(content or rendered or ""))
            try:
                finish_run(
                    run_id,
                    status="success",
                    error_message=None,
                    output_type=str(normalized.get("type") or "text"),
                    grounded=normalized.get("grounded"),
                )
                run_finished = True
            except Exception:
                logger.exception("Failed to finish run")
            return (
                OrchestratorResult(
                    run_id=run_id,
                    final_answer=_non_empty_answer(rendered or last_content or ""),
                    normalized_response=normalized,
                    tool_trace=tool_trace,
                ),
                messages,
            )
        except Exception:
            fallback = last_content.strip() or "I couldn't complete the task within the tool step limit."
            try:
                if not run_finished:
                    finish_run(
                        run_id,
                        status="error",
                        error_message=redact_text(fallback, max_len=1200),
                        output_type="text",
                        grounded=None,
                    )
            except Exception:
                logger.exception("Failed to finish fallback error run")
            return (
                OrchestratorResult(
                    run_id=run_id,
                    final_answer=fallback,
                    normalized_response={
                        "type": "text",
                        "answer": fallback,
                        "blocks": [{"type": "text", "content": fallback, "language": "", "filename": ""}],
                        "sources": [],
                        "grounded": None,
                        "next_step": "",
                    },
                    tool_trace=tool_trace,
                ),
                messages,
            )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(tz=timezone.utc).isoformat()
