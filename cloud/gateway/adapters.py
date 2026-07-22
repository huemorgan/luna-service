"""Billing-grade provider usage parsing (039/004).

One adapter per billed route (see `cloud/gateway/route_catalog.py`). These
replace the regex `UsageScanner` as the *financial* source of usage; the
legacy `usage_events` dual-write remains telemetry only.

Collectors are incremental and SSE-chunk-split tolerant: they buffer at the
line level, never assume a `data:` frame arrives whole, and take the max of
repeated cumulative counters so duplicated frames can never double-count.
Only usage counters, ids and the model name are retained — never message
content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Never buffer unbounded response bodies: full-parse small JSON bodies, and
# for oversized ones (large embedding arrays) fall back to head/tail scans —
# provider usage objects sit at the start or end of the body.
_MAX_FULL_JSON = 2 * 1024 * 1024
_HEAD_KEEP = 16 * 1024
_TAIL_KEEP = 96 * 1024

_OUTPUT_CEILING_DEFAULT = 8192


@dataclass
class UsageFacts:
    """Normalized billable dimensions for one provider attempt."""

    dimensions: dict[str, int] = field(default_factory=dict)
    model: str | None = None
    provider_request_id: str | None = None
    provider_response_id: str | None = None
    usage_seen: bool = False


def provider_for_adapter(adapter: str) -> str:
    return adapter.split(".", 1)[0]


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _first_json_value(text: str, key: str):
    """Decode the first JSON value following `"key":` in raw text. Tolerates
    surrounding garbage — used for head/tail scans of oversized bodies."""
    needle = f'"{key}"'
    start = text.find(needle)
    if start < 0:
        return None
    colon = text.find(":", start + len(needle))
    if colon < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text, colon + 1)
    except ValueError:
        return None
    return value


class _BoundedBody:
    """Accumulates a response body with bounded memory."""

    def __init__(self) -> None:
        self._full = bytearray()
        self._head = bytearray()
        self._tail = bytearray()
        self.total = 0
        self.overflowed = False

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        if not self.overflowed:
            self._full.extend(chunk)
            if len(self._full) > _MAX_FULL_JSON:
                self.overflowed = True
                self._head = bytearray(self._full[:_HEAD_KEEP])
                self._tail = bytearray(self._full[-_TAIL_KEEP:])
                self._full.clear()
                return
        else:
            if len(self._head) < _HEAD_KEEP:
                self._head.extend(chunk[: _HEAD_KEEP - len(self._head)])
            self._tail.extend(chunk)
            if len(self._tail) > _TAIL_KEEP:
                del self._tail[: len(self._tail) - _TAIL_KEEP]

    def parse(self) -> dict | None:
        if self.overflowed:
            return None
        try:
            data = json.loads(bytes(self._full))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def scan(self, key: str):
        """Head-then-tail scan for oversized bodies."""
        for buf in (self._head, self._tail):
            value = _first_json_value(buf.decode("utf-8", "replace"), key)
            if value is not None:
                return value
        return None


class _SseLines:
    """Line splitter that survives arbitrary chunk boundaries."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf.extend(chunk)
        *complete, rest = self._buf.split(b"\n")
        self._buf = bytearray(rest)
        return complete

    def flush(self) -> list[bytes]:
        if not self._buf:
            return []
        line, self._buf = bytes(self._buf), bytearray()
        return [line]


def _sse_data(line: bytes) -> dict | None:
    line = line.strip()
    if not line.startswith(b"data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == b"[DONE]":
        return None
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class UsageCollector:
    """Base collector: routes chunks to SSE or JSON handling and produces
    normalized UsageFacts. Subclasses parse provider-specific frames into
    `self._raw` (max-merge) and normalize in `_dimensions()`."""

    request_id_header = "x-request-id"

    def __init__(self, content_type: str) -> None:
        self._sse = _SseLines() if "text/event-stream" in content_type else None
        self._body = _BoundedBody() if self._sse is None else None
        self._raw: dict[str, int] = {}
        self.model: str | None = None
        self.response_id: str | None = None
        self.usage_seen = False

    # -- provider-specific hooks ------------------------------------------
    def _handle_event(self, data: dict) -> None:  # SSE frame
        raise NotImplementedError

    def _handle_document(self, data: dict) -> None:  # whole JSON body
        raise NotImplementedError

    def _handle_oversized(self, body: _BoundedBody) -> None:
        usage = body.scan("usage")
        if isinstance(usage, dict):
            self._merge_usage(usage)
        model = body.scan("model")
        if isinstance(model, str):
            self.model = self.model or model
        rid = body.scan("id")
        if isinstance(rid, str):
            self.response_id = self.response_id or rid

    def _dimensions(self) -> dict[str, int]:
        raise NotImplementedError

    # -- shared machinery ---------------------------------------------------
    def _merge_usage(self, usage: dict) -> None:
        """Max-merge cumulative counters — duplicate/replayed frames can only
        repeat a count, never add to it."""
        for key, value in usage.items():
            iv = _int_or_none(value)
            if iv is None:
                # Anthropic nests newer cache-creation detail one level down.
                if key == "cache_creation" and isinstance(value, dict):
                    total = sum(v for v in value.values() if _int_or_none(v) is not None)
                    key, iv = "cache_creation_input_tokens", total
                else:
                    continue
            self._raw[key] = max(self._raw.get(key, 0), iv)
            self.usage_seen = True

    def _capture_identity(self, data: dict) -> None:
        model = data.get("model")
        if isinstance(model, str) and model:
            self.model = model
        rid = data.get("id")
        if isinstance(rid, str) and rid:
            self.response_id = rid

    def feed(self, chunk: bytes) -> None:
        try:
            if self._sse is not None:
                for line in self._sse.feed(chunk):
                    data = _sse_data(line)
                    if data is not None:
                        self._handle_event(data)
            else:
                self._body.feed(chunk)
        except Exception:  # noqa: BLE001 — usage parsing must never break the stream
            pass

    def finish(self, status_code: int, headers) -> UsageFacts:
        try:
            if self._sse is not None:
                for line in self._sse.flush():
                    data = _sse_data(line)
                    if data is not None:
                        self._handle_event(data)
            else:
                doc = self._body.parse()
                if doc is not None:
                    self._handle_document(doc)
                elif self._body.overflowed:
                    self._handle_oversized(self._body)
        except Exception:  # noqa: BLE001
            pass
        request_id = None
        try:
            request_id = headers.get(self.request_id_header) or None
        except Exception:  # noqa: BLE001
            pass
        # Dimensions are returned even for failed attempts — the enforcement
        # layer bills only successful attempts and records failed-attempt
        # provider cost as Luna-absorbed.
        dims = self._dimensions() if self.usage_seen else {}
        return UsageFacts(
            dimensions={k: v for k, v in dims.items() if v > 0},
            model=self.model,
            provider_request_id=request_id,
            provider_response_id=self.response_id,
            usage_seen=self.usage_seen,
        )


class AnthropicMessagesCollector(UsageCollector):
    """POST /v1/messages — JSON or SSE. Anthropic reports uncached input,
    cache reads and cache writes as disjoint counters (no double counting)."""

    request_id_header = "request-id"

    def _handle_event(self, data: dict) -> None:
        etype = data.get("type")
        if etype == "message_start":
            message = data.get("message")
            if isinstance(message, dict):
                self._capture_identity(message)
                usage = message.get("usage")
                if isinstance(usage, dict):
                    self._merge_usage(usage)
        elif etype == "message_delta":
            usage = data.get("usage")
            if isinstance(usage, dict):
                self._merge_usage(usage)

    def _handle_document(self, data: dict) -> None:
        self._capture_identity(data)
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._merge_usage(usage)

    def _dimensions(self) -> dict[str, int]:
        return {
            "input_tokens": self._raw.get("input_tokens", 0),
            "output_tokens": self._raw.get("output_tokens", 0),
            "cache_creation_input_tokens": self._raw.get("cache_creation_input_tokens", 0),
            "cache_read_input_tokens": self._raw.get("cache_read_input_tokens", 0),
        }


class OpenAIChatCollector(UsageCollector):
    """POST /v1/chat/completions — JSON or SSE (usage frame arrives only with
    stream_options.include_usage, which the gateway injects on managed
    streams). OpenAI's prompt_tokens INCLUDES cached tokens — normalization
    subtracts them so cached input is never billed twice."""

    def _handle_event(self, data: dict) -> None:
        self._capture_identity(data)
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._merge_flat_usage(usage)

    def _handle_document(self, data: dict) -> None:
        self._capture_identity(data)
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._merge_flat_usage(usage)

    def _handle_oversized(self, body: _BoundedBody) -> None:
        usage = body.scan("usage")
        if isinstance(usage, dict):
            self._merge_flat_usage(usage)

    def _merge_flat_usage(self, usage: dict) -> None:
        flat = dict(usage)
        details = flat.pop("prompt_tokens_details", None)
        if isinstance(details, dict):
            cached = _int_or_none(details.get("cached_tokens"))
            if cached is not None:
                flat["cached_tokens"] = cached
        details = flat.pop("completion_tokens_details", None)
        if isinstance(details, dict):
            reasoning = _int_or_none(details.get("reasoning_tokens"))
            if reasoning is not None:
                flat["reasoning_tokens"] = reasoning
        self._merge_usage(flat)

    def _dimensions(self) -> dict[str, int]:
        prompt = self._raw.get("prompt_tokens", 0)
        cached = min(self._raw.get("cached_tokens", 0), prompt)
        return {
            "input_tokens": prompt - cached,
            "cached_input_tokens": cached,
            "output_tokens": self._raw.get("completion_tokens", 0),
        }


class XAIChatCollector(OpenAIChatCollector):
    """xAI's usage object EXCLUDES reasoning tokens from completion_tokens
    (completion_tokens_details.reasoning_tokens is disjoint), but bills them at
    the output rate — verified against usage.cost_in_usd_ticks. OpenAI folds
    reasoning into completion_tokens, so only xAI adds it back."""

    def _dimensions(self) -> dict[str, int]:
        dims = super()._dimensions()
        dims["output_tokens"] += self._raw.get("reasoning_tokens", 0)
        return dims


class OpenAIEmbeddingsCollector(OpenAIChatCollector):
    """POST /v1/embeddings — always JSON; responses can be many MB, hence the
    oversized-body scan path. Only input tokens exist."""

    def _dimensions(self) -> dict[str, int]:
        return {"input_tokens": self._raw.get("prompt_tokens", 0)}


class GeminiGenerateCollector(UsageCollector):
    """POST /models/{model}:generateContent — JSON (streamGenerateContent is
    not a billed route). Gemini reports `usageMetadata` with per-modality
    output detail: IMAGE candidate tokens carry the image-output rate, the
    remainder plus thinking tokens the text-output rate. Inline-image
    responses are MBs of base64, so the oversized scan targets
    `usageMetadata`. When the per-modality detail is absent, every candidate
    token is treated as an image token — this is an image-model-only route,
    and the expensive dimension is the safe default."""

    def _handle_event(self, data: dict) -> None:
        self._handle_document(data)

    def _handle_document(self, data: dict) -> None:
        model = data.get("modelVersion")
        if isinstance(model, str) and model:
            self.model = model
        rid = data.get("responseId")
        if isinstance(rid, str) and rid:
            self.response_id = rid
        usage = data.get("usageMetadata")
        if isinstance(usage, dict):
            self._merge_gemini_usage(usage)

    def _handle_oversized(self, body: _BoundedBody) -> None:
        usage = body.scan("usageMetadata")
        if isinstance(usage, dict):
            self._merge_gemini_usage(usage)
        model = body.scan("modelVersion")
        if isinstance(model, str):
            self.model = self.model or model
        rid = body.scan("responseId")
        if isinstance(rid, str):
            self.response_id = self.response_id or rid

    def _merge_gemini_usage(self, usage: dict) -> None:
        flat: dict[str, int] = {}
        for src, dst in (
            ("promptTokenCount", "prompt_tokens"),
            ("candidatesTokenCount", "candidates_tokens"),
            ("thoughtsTokenCount", "thoughts_tokens"),
        ):
            value = _int_or_none(usage.get(src))
            if value is not None:
                flat[dst] = value
        details = usage.get("candidatesTokensDetails")
        if isinstance(details, list):
            image = sum(
                _int_or_none(d.get("tokenCount")) or 0
                for d in details
                if isinstance(d, dict) and d.get("modality") == "IMAGE"
            )
            flat["candidates_image_tokens"] = image
            self._raw.setdefault("candidates_details_seen", 1)
        self._merge_usage(flat)

    def _dimensions(self) -> dict[str, int]:
        candidates = self._raw.get("candidates_tokens", 0)
        if self._raw.get("candidates_details_seen"):
            image = min(self._raw.get("candidates_image_tokens", 0), candidates)
        else:
            image = candidates
        return {
            "input_tokens": self._raw.get("prompt_tokens", 0),
            "output_image_tokens": image,
            "output_text_tokens": candidates - image + self._raw.get("thoughts_tokens", 0),
        }


class OpenAIImagesCollector(UsageCollector):
    """POST /images/generations and /images/edits — JSON, or SSE when the
    request streams partial images (usage rides the *.completed event).
    `usage` splits input into text/image via input_tokens_details;
    output_tokens are image-output tokens. b64_json payloads are MBs, so
    the oversized scan matters. Missing detail bills all input as text —
    the cheaper dimension, and the total is preserved."""

    def _handle_event(self, data: dict) -> None:
        self._handle_document(data)

    def _handle_document(self, data: dict) -> None:
        self._capture_identity(data)
        usage = data.get("usage")
        if isinstance(usage, dict):
            self._merge_images_usage(usage)

    def _handle_oversized(self, body: _BoundedBody) -> None:
        usage = body.scan("usage")
        if isinstance(usage, dict):
            self._merge_images_usage(usage)

    def _merge_images_usage(self, usage: dict) -> None:
        flat = dict(usage)
        details = flat.pop("input_tokens_details", None)
        if isinstance(details, dict):
            for src, dst in (("text_tokens", "input_text_tokens"),
                             ("image_tokens", "input_image_tokens")):
                value = _int_or_none(details.get(src))
                if value is not None:
                    flat[dst] = value
        self._merge_usage(flat)

    def _dimensions(self) -> dict[str, int]:
        total_in = self._raw.get("input_tokens", 0)
        text = self._raw.get("input_text_tokens", total_in)
        return {
            "input_text_tokens": min(text, total_in) if total_in else text,
            "input_image_tokens": self._raw.get("input_image_tokens", 0),
            "output_tokens": self._raw.get("output_tokens", 0),
        }


_COLLECTORS = {
    "anthropic.messages": AnthropicMessagesCollector,
    "openai.chat": OpenAIChatCollector,
    "openai.embeddings": OpenAIEmbeddingsCollector,
    # xAI is OpenAI-compatible on the wire, but its completion_tokens excludes
    # billed reasoning tokens — XAIChatCollector adds them back.
    "xai.chat": XAIChatCollector,
    # Gemini's OpenAI-compat surface (050) reports OpenAI-shaped usage.
    "gemini.chat": OpenAIChatCollector,
    "gemini.generate": GeminiGenerateCollector,
    "openai.images": OpenAIImagesCollector,
}

# Adapters speaking the OpenAI chat protocol (usage shape + stream_options).
_OPENAI_CHAT_COMPAT = ("openai.chat", "xai.chat", "gemini.chat")


def make_collector(adapter: str, content_type: str) -> UsageCollector:
    return _COLLECTORS[adapter](content_type)


def _multipart_field(body: bytes, name: str) -> str | None:
    """Scan a multipart body for one small text field. Bounded on purpose:
    first match only, value capped at 200 bytes, file parts never decoded."""
    pattern = rb'name="' + re.escape(name.encode()) + rb'"\r\n\r\n([^\r\n]{1,200})'
    match = re.search(pattern, body)
    if match is None:
        return None
    try:
        return match.group(1).decode("utf-8").strip() or None
    except UnicodeDecodeError:
        return None


def extract_model(
    adapter: str, body_json: dict | None, path: str,
    content_type: str = "", body: bytes = b"",
) -> str | None:
    """Requested model for tier/coverage resolution. Most adapters carry it in
    the JSON body; Gemini encodes it in the URL path
    (/models/{model}:generateContent) and multipart uploads (images/edits)
    carry it as a form field."""
    if adapter == "gemini.generate":
        segment = path.rstrip("/").rpartition("/")[2]
        return segment.partition(":")[0] or None
    if isinstance(body_json, dict):
        model = body_json.get("model")
        if isinstance(model, str) and model:
            return model
    if adapter == "openai.images" and "multipart/form-data" in (content_type or ""):
        return _multipart_field(body, "model")
    return None


def estimate_dimensions(
    adapter: str, body_json: dict | None, body_len: int,
    *, output_ceiling: int = _OUTPUT_CEILING_DEFAULT,
) -> dict[str, int]:
    """Pre-flight exposure estimate: serialized input at ~4 bytes/token plus
    the requested output maximum (or the configured ceiling when the request
    carries none). Settlement always uses real provider usage."""
    est_input = -(-body_len // 4) if body_len else 1
    body = body_json if isinstance(body_json, dict) else {}
    if adapter == "openai.embeddings":
        return {"input_tokens": est_input}
    if adapter == "gemini.generate":
        # Reference images inflate body_len enormously — input is text-priced,
        # so cap the estimate; the hold is dominated by one 4K output image
        # (2000 image tokens). Settlement uses real usage.
        return {"input_tokens": min(est_input, 4000), "output_image_tokens": 2000}
    if adapter == "openai.images":
        n = _int_or_none(body.get("n")) or 1
        # Worst case: high-quality 1024x1536 ≈ 6240 output tokens per image.
        return {"input_text_tokens": min(est_input, 4000), "output_tokens": 6240 * n}
    if adapter == "anthropic.messages":
        max_out = _int_or_none(body.get("max_tokens"))
    else:
        max_out = _int_or_none(body.get("max_completion_tokens")) or _int_or_none(
            body.get("max_tokens")
        )
    if max_out is None or max_out <= 0:
        max_out = output_ceiling
    return {"input_tokens": est_input, "output_tokens": max_out}


def prepare_managed_body(adapter: str, body_json: dict | None, body: bytes) -> bytes:
    """Managed-flow request rewrite: OpenAI chat streams only report usage
    when stream_options.include_usage is set — inject it so every managed
    stream is billable. Returns the body unchanged otherwise."""
    if adapter not in _OPENAI_CHAT_COMPAT or not isinstance(body_json, dict):
        return body
    if body_json.get("stream") is not True:
        return body
    options = body_json.get("stream_options")
    if isinstance(options, dict) and options.get("include_usage") is True:
        return body
    patched = dict(body_json)
    patched["stream_options"] = {
        **(options if isinstance(options, dict) else {}),
        "include_usage": True,
    }
    return json.dumps(patched).encode()
