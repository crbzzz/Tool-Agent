"""Small wrapper around the official `mistralai` SDK for Mistral Agents."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _first(seq: Any, default: Any = None) -> Any:
    try:
        return seq[0]
    except Exception:
        return default


def _parse_json_maybe(value: Any) -> Any:
    if isinstance(value, str):
        value_str = value.strip()
        if not value_str:
            return {}
        try:
            return json.loads(value_str)
        except Exception:
            return {"_raw": value}
    if isinstance(value, dict):
        return value
    return {"_raw": value}


def _to_dict_maybe(obj: Any) -> Any:
    """Best-effort conversion of SDK/pydantic objects to plain dict/list."""

    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_dict_maybe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_dict_maybe(x) for x in obj]
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        try:
            return _to_dict_maybe(model_dump())
        except Exception:
            pass
    as_dict = getattr(obj, "dict", None)
    if callable(as_dict):
        try:
            return _to_dict_maybe(as_dict())
        except Exception:
            pass
    # Fallback: attempt attribute extraction for common fields
    out: Dict[str, Any] = {}
    for key in ("id", "type", "name", "arguments", "function", "tool_calls", "content", "role"):
        val = getattr(obj, key, None)
        if val is not None:
            out[key] = _to_dict_maybe(val)
    return out or {"_raw": repr(obj)}


@dataclass(frozen=True)
class NormalizedToolCall:
    """Normalized representation of a tool call."""

    name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None


def normalize_tool_calls(tool_calls: Any) -> List[NormalizedToolCall]:
    """Normalize tool call objects from different SDK shapes into a standard list."""

    if not tool_calls:
        return []

    calls: List[NormalizedToolCall] = []
    if not isinstance(tool_calls, list):
        tool_calls = [tool_calls]

    for call in tool_calls:
        call_id = _get(call, "id", None)
        fn = _get(call, "function", None) or call
        name = _get(fn, "name", None) or _get(call, "name", None)
        args = _get(fn, "arguments", None) or _get(call, "arguments", None)
        if name is None:
            fn2 = _get(call, "function", None)
            name = _get(fn2, "name", None)
            args = _get(fn2, "arguments", None)
        if not name:
            continue
        calls.append(NormalizedToolCall(name=str(name), arguments=_parse_json_maybe(args) or {}, call_id=call_id))

    return calls


def extract_assistant_message(response: Any) -> Tuple[str, List[NormalizedToolCall]]:
    """Extract assistant content and tool calls from an agents.complete response."""

    msg = None
    choices = _get(response, "choices", None)
    if choices is not None:
        choice0 = _first(choices)
        msg = _get(choice0, "message", None) or _get(choice0, "delta", None)
    if msg is None:
        msg = _get(response, "message", None)

    content = _get(msg, "content", "")
    if content is None:
        content = ""

    tool_calls = _get(msg, "tool_calls", None) or _get(response, "tool_calls", None)
    normalized = normalize_tool_calls(tool_calls)
    return str(content), normalized


def extract_assistant_message_dict(response: Any) -> Dict[str, Any]:
    """Extract a JSON-serializable assistant message dict suitable to append into `messages`."""

    msg = None
    choices = _get(response, "choices", None)
    if choices is not None:
        choice0 = _first(choices)
        msg = _get(choice0, "message", None) or _get(choice0, "delta", None)
    if msg is None:
        msg = _get(response, "message", None)

    content = _get(msg, "content", "")
    tool_calls = _get(msg, "tool_calls", None) or _get(response, "tool_calls", None)

    assistant: Dict[str, Any] = {"role": "assistant", "content": "" if content is None else str(content)}
    if tool_calls:
        assistant["tool_calls"] = _to_dict_maybe(tool_calls)
    return assistant


class MistralAgentsClient:
    """Wrapper for calling a pre-configured Mistral Agent."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str) -> Any:
        try:
            from mistralai import Mistral  # type: ignore

            return Mistral(api_key=api_key)
        except Exception:
            try:
                from mistralai.client import MistralClient  # type: ignore

                return MistralClient(api_key=api_key)
            except Exception as exc:
                raise RuntimeError(
                    "Unable to import Mistral SDK client. Ensure `mistralai` is installed."
                ) from exc

    def complete(self, agent_id: str, messages: List[Dict[str, Any]]) -> Any:
        """Call `client.agents.complete` and return the raw SDK response."""

        agents = getattr(self._client, "agents", None)
        if agents is None:
            raise RuntimeError("Mistral SDK client does not expose `.agents`. SDK may be incompatible.")

        complete_fn = getattr(agents, "complete", None)
        if complete_fn is None:
            raise RuntimeError("Mistral SDK client does not expose `.agents.complete`. SDK may be incompatible.")

        return complete_fn(agent_id=agent_id, messages=messages)

    def complete_with_role_fallback(self, agent_id: str, messages: List[Dict[str, Any]]) -> Any:
        """Complete with best-effort role compatibility."""

        try:
            return self.complete(agent_id=agent_id, messages=messages)
        except Exception as e1:
            msg1 = str(e1)
            logger.warning("agents.complete failed; retrying with role fallback: %s", msg1)

        messages2 = []
        for m in messages:
            if m.get("role") == "developer":
                messages2.append({**m, "role": "system"})
            else:
                messages2.append(m)
        try:
            return self.complete(agent_id=agent_id, messages=messages2)
        except Exception as e2:
            msg2 = str(e2)
            logger.warning("agents.complete failed again; retrying with policy folded into user: %s", msg2)

        policy_parts: List[str] = []
        user_parts: List[Dict[str, Any]] = []
        for m in messages:
            if m.get("role") in ("developer", "system"):
                policy_parts.append(str(m.get("content", "")))
            else:
                user_parts.append(m)
        if user_parts and policy_parts:
            first = user_parts[0]
            if first.get("role") != "user":
                user_parts.insert(0, {"role": "user", "content": ""})
                first = user_parts[0]
            first_content = str(first.get("content", ""))
            folded = "\n\n".join(["POLICY:", "\n".join(policy_parts), "USER:", first_content]).strip()
            user_parts[0] = {**first, "content": folded}

        return self.complete(agent_id=agent_id, messages=user_parts)
