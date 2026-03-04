"""Parsing/validation/normalization helpers for assistant outputs.

This module is intentionally dependency-free (stdlib only) to keep the backend
robust even if the model occasionally returns JSON wrapped in text or code fences.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

import ast

from rag.agent.mistral_client import NormalizedToolCall


class ModelOutputError(Exception):
    pass


class ModelOutputParseError(ModelOutputError):
    pass


class ModelOutputValidationError(ModelOutputError):
    pass


ResponseType = Literal["text", "code", "mixed"]


@dataclass(frozen=True)
class NormalizedFinalBlock:
    type: Literal["text", "code"]
    content: str
    language: str = ""
    filename: str = ""


@dataclass(frozen=True)
class NormalizedFinalResponse:
    type: ResponseType
    answer: str
    blocks: List[NormalizedFinalBlock]
    sources: List[Any]
    grounded: bool
    next_step: str = ""


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_+-]*\s*\n(?P<body>[\s\S]*?)\n```\s*$", re.MULTILINE)


def _strip_outer_code_fence(text: str) -> str:
    s = (text or "").strip()
    if not s.startswith("```"):
        return s
    m = _FENCE_RE.match(s)
    if not m:
        return s
    return (m.group("body") or "").strip()


def extract_first_json_object(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from a string.

    Accepts JSON wrapped in markdown code fences or surrounded by other text.
    Returns a dict only; raises if no dict is found.
    """

    raw = _strip_outer_code_fence(text)
    s = raw.strip()
    if not s:
        raise ModelOutputParseError("empty output")

    decoder = json.JSONDecoder()

    def _try_decode_dict(payload: str, start: int = 0) -> Optional[Dict[str, Any]]:
        try:
            obj, _end = decoder.raw_decode(payload, start)
        except Exception:
            return None
        return obj if isinstance(obj, dict) else None

    # Fast path: exact JSON object
    if s.startswith("{"):
        decoded = _try_decode_dict(s, 0)
        if decoded is not None:
            return decoded

    # Robust scan: find any JSON object starting at a '{'
    for idx, ch in enumerate(s):
        if ch != "{":
            continue
        decoded = _try_decode_dict(s, idx)
        if decoded is not None:
            return decoded

    # Lenient fallback: models often emit "JSON-ish" with unescaped newlines inside strings.
    candidate = _extract_first_braced_object(s)
    if candidate:
        decoded = _parse_jsonish_dict(candidate)
        if decoded is not None:
            return decoded

    raise ModelOutputParseError("no JSON object found")


_SMART_QUOTES = {
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u00ab": '"',
    "\u00bb": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u2032": "'",
}


def _replace_smart_quotes(s: str) -> str:
    out = s
    for k, v in _SMART_QUOTES.items():
        out = out.replace(k, v)
    return out


def _escape_controls_in_json_strings(payload: str) -> str:
    """Repair JSON-ish strings by escaping invalid characters.

    Common LLM failure modes:
    - literal newlines/tabs inside a quoted JSON string (must be escaped)
    - quotes inside a quoted string (e.g. ... : "bonjour" ...) without escaping

    This pass keeps the overall structure intact and only transforms content
    *inside* strings.
    """

    out: List[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(payload):
        ch = payload[i]
        if in_string:
            if escape:
                out.append(ch)
                escape = False
                i += 1
                continue
            if ch == "\\":
                out.append(ch)
                escape = True
                i += 1
                continue
            if ch == '"':
                # Heuristic: if the next non-whitespace char is a valid JSON string
                # terminator, treat this quote as the end of the string. Otherwise,
                # it's likely an inner quote emitted by the model, so escape it.
                j = i + 1
                while j < len(payload) and payload[j] in " \t\r\n":
                    j += 1
                next_ch = payload[j] if j < len(payload) else ""
                if next_ch in (":", ",", "}", "]"):
                    out.append(ch)
                    in_string = False
                else:
                    out.append('\\"')
                i += 1
                continue
            if ch == "\r":
                # Normalize CRLF/CR to \n
                if i + 1 < len(payload) and payload[i + 1] == "\n":
                    i += 1
                out.append("\\n")
                i += 1
                continue
            if ch == "\n":
                out.append("\\n")
                i += 1
                continue
            if ch == "\t":
                out.append("\\t")
                i += 1
                continue
            if ch == "\b":
                out.append("\\b")
                i += 1
                continue
            if ch == "\f":
                out.append("\\f")
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        # Not in string
        if ch == '"':
            out.append(ch)
            in_string = True
            i += 1
            continue
        out.append(ch)
        i += 1

    return "".join(out)


_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _extract_first_braced_object(text: str) -> str:
    """Extract first {...} region using brace matching, tolerant to invalid JSON.

    This ignores braces that appear inside quoted strings.
    Returns "" if none found.
    """

    if not text:
        return ""

    start = text.find("{")
    while start >= 0:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                depth += 1
                continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
                continue

        # No closing brace found; try next '{'
        start = text.find("{", start + 1)
    return ""


def _parse_jsonish_dict(candidate: str) -> Optional[Dict[str, Any]]:
    """Best-effort parse of JSON-ish dict emitted by LLMs."""

    if not isinstance(candidate, str) or not candidate.strip():
        return None

    s = candidate.strip()
    # Try strict first.
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Repair common issues: smart quotes, unescaped controls in strings, trailing commas.
    repaired = _replace_smart_quotes(s)
    repaired = _escape_controls_in_json_strings(repaired)
    repaired = _TRAILING_COMMA_RE.sub(r"\\1", repaired)

    try:
        obj = json.loads(repaired)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass

    # Last resort: python literal eval (after mapping JSON tokens). This is only used
    # on an extracted object substring (not arbitrary code) but we still keep it tight.
    pyish = repaired
    pyish = re.sub(r"\btrue\b", "True", pyish)
    pyish = re.sub(r"\bfalse\b", "False", pyish)
    pyish = re.sub(r"\bnull\b", "None", pyish)
    try:
        obj2 = ast.literal_eval(pyish)
        return obj2 if isinstance(obj2, dict) else None
    except Exception:
        return None


def _strip_markdown_fences_in_code(code: str) -> str:
    """Remove ``` fences if the model included them inside code content."""

    s = (code or "")
    s2 = _strip_outer_code_fence(s)
    # Also handle the common case where the model includes multiple fenced blocks.
    if "```" not in s2:
        return s2

    parts: List[str] = []
    remaining = s2
    while True:
        start = remaining.find("```")
        if start < 0:
            parts.append(remaining)
            break
        parts.append(remaining[:start])
        remaining = remaining[start:]
        m = _FENCE_RE.match(remaining.strip())
        if m:
            parts.append((m.group("body") or ""))
            # If it matched the whole string, we're done.
            break
        # If it didn't match, drop the fence marker and continue.
        remaining = remaining.replace("```", "", 1)
    return "".join(parts).strip("\n")


def parse_tool_calls_from_text(text: str) -> List[NormalizedToolCall]:
    """Parse tool calls from assistant content (JSON-in-text fallback)."""

    try:
        obj = extract_first_json_object(text)
    except ModelOutputParseError:
        return []

    def _one(tc: Any) -> Optional[NormalizedToolCall]:
        if not isinstance(tc, dict):
            return None
        name = tc.get("name")
        args = tc.get("arguments")
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(args, dict):
            return None
        return NormalizedToolCall(name=name.strip(), arguments=args, call_id=None)

    calls: List[NormalizedToolCall] = []

    # Contract A: {"tool_call": {"name":..., "arguments":{...}}}
    if isinstance(obj.get("tool_call"), dict):
        one = _one(obj.get("tool_call"))
        if one:
            calls.append(one)

    # Variant: {"tool_calls": [{"name":..., "arguments":{...}}]}
    if isinstance(obj.get("tool_calls"), list):
        for tc in obj.get("tool_calls"):
            one = _one(tc)
            if one:
                calls.append(one)

    # Variant: {"name":..., "arguments":{...}}
    if not calls:
        one = _one(obj)
        if one:
            calls.append(one)

    return calls


def normalize_final_response_from_obj(obj: Dict[str, Any]) -> NormalizedFinalResponse:
    """Validate + normalize the final response object (Contract B).

    This is strict enough to keep the UI stable but also tolerates missing
    optional fields by applying safe defaults.
    """

    if not isinstance(obj, dict):
        raise ModelOutputValidationError("final response must be a JSON object")
    if "tool_call" in obj or "tool_calls" in obj:
        raise ModelOutputValidationError("expected final response, got tool_call")

    raw_type = obj.get("type")
    blocks_raw = obj.get("blocks")
    answer_raw = obj.get("answer")

    # Best-effort infer if type missing.
    if raw_type not in ("text", "code", "mixed"):
        if isinstance(blocks_raw, list) and blocks_raw:
            raw_type = "mixed" if len(blocks_raw) > 1 else "code"
        elif isinstance(obj.get("content"), str) and obj.get("content"):
            raw_type = "text"
        else:
            raw_type = "text"
    rtype: ResponseType = raw_type  # type: ignore[assignment]

    sources = obj.get("sources")
    if sources is None:
        sources_list: List[Any] = []
    elif isinstance(sources, list):
        sources_list = sources
    else:
        # Accept a single value, but normalize to list.
        sources_list = [sources]

    grounded = obj.get("grounded")
    if not isinstance(grounded, bool):
        grounded_bool = False
    else:
        grounded_bool = grounded

    next_step = obj.get("next_step")
    next_step_str = next_step if isinstance(next_step, str) else ""

    answer = ""
    if isinstance(answer_raw, str):
        answer = answer_raw
    elif isinstance(obj.get("content"), str):
        answer = str(obj.get("content") or "")

    blocks: List[NormalizedFinalBlock] = []

    def _add_text_block(content: Any) -> None:
        if content is None:
            return
        if not isinstance(content, str):
            content = str(content)
        blocks.append(NormalizedFinalBlock(type="text", content=content))

    def _add_code_block(language: Any, filename: Any, content: Any) -> None:
        lang = language if isinstance(language, str) else ""
        fname = filename if isinstance(filename, str) else ""
        body = content if isinstance(content, str) else ""
        body = _strip_markdown_fences_in_code(body).strip("\n")
        if not lang.strip():
            raise ModelOutputValidationError("code block missing non-empty language")
        if not body.strip():
            raise ModelOutputValidationError("code block content is empty")
        blocks.append(
            NormalizedFinalBlock(
                type="code",
                language=lang.strip(),
                filename=fname,
                content=body,
            )
        )

    # Legacy top-level code fields
    legacy_language = obj.get("language")
    legacy_filename = obj.get("filename")
    legacy_content = obj.get("content")
    if rtype == "code" and legacy_language and legacy_content and not blocks_raw:
        _add_code_block(legacy_language, legacy_filename or "", legacy_content)

    # Blocks for mixed/code
    if blocks_raw is not None:
        if not isinstance(blocks_raw, list):
            raise ModelOutputValidationError("blocks must be a list")

        for b in blocks_raw:
            if not isinstance(b, dict):
                raise ModelOutputValidationError("each block must be an object")
            btype = b.get("type")
            if btype == "text":
                _add_text_block(b.get("content"))
            elif btype == "code":
                _add_code_block(b.get("language"), b.get("filename", ""), b.get("content"))
            else:
                raise ModelOutputValidationError("invalid block type")

    # If type=text but blocks provided, still keep them (UI may choose to render).
    if rtype == "text":
        if not isinstance(answer, str):
            answer = str(answer)
        if not answer and blocks:
            # Derive answer from text blocks, keep code blocks for completeness.
            texts = [blk.content for blk in blocks if blk.type == "text" and blk.content.strip()]
            if texts:
                answer = "\n\n".join(texts)
        return NormalizedFinalResponse(
            type="text",
            answer=answer,
            blocks=blocks,
            sources=sources_list,
            grounded=grounded_bool,
            next_step=next_step_str,
        )

    if rtype == "code":
        code_blocks = [blk for blk in blocks if blk.type == "code"]
        if len(code_blocks) != 1:
            raise ModelOutputValidationError("type=code must have exactly one code block")
        return NormalizedFinalResponse(
            type="code",
            answer=answer or "",
            blocks=blocks,
            sources=sources_list,
            grounded=grounded_bool,
            next_step=next_step_str,
        )

    # mixed
    if not isinstance(blocks_raw, list):
        raise ModelOutputValidationError("type=mixed requires blocks")
    if not blocks:
        raise ModelOutputValidationError("type=mixed requires non-empty blocks")
    # Validate code blocks content already enforced in _add_code_block
    return NormalizedFinalResponse(
        type="mixed",
        answer=answer or "",
        blocks=blocks,
        sources=sources_list,
        grounded=grounded_bool,
        next_step=next_step_str,
    )


def parse_final_response_from_text(text: str) -> Optional[NormalizedFinalResponse]:
    """Parse a final response JSON object from assistant text.

    Returns None if the text is not parseable as JSON.
    Raises ModelOutputValidationError if JSON exists but violates the contract.
    """

    try:
        obj = extract_first_json_object(text)
    except ModelOutputParseError:
        return None
    return normalize_final_response_from_obj(obj)


def normalized_response_to_markdown(resp: NormalizedFinalResponse) -> str:
    """Convert normalized response to a markdown-ish string for legacy UIs."""

    parts: List[str] = []
    if isinstance(resp.answer, str) and resp.answer.strip():
        parts.append(resp.answer.strip())

    # Render blocks.
    for blk in resp.blocks:
        if blk.type == "text":
            if blk.content.strip():
                parts.append(blk.content.strip())
            continue
        if blk.type == "code":
            lang = (blk.language or "").strip() or "text"
            code = (blk.content or "").rstrip("\n")
            parts.append(f"```{lang}\n{code}\n```")

    if resp.next_step.strip():
        parts.append(f"\nNext: {resp.next_step.strip()}")

    return "\n\n".join([p for p in parts if p is not None]).strip()
