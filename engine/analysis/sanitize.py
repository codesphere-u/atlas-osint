"""Untrusted-content handling for the AI analysis layer.

Everything collected from the web is *data*, never instructions. Before any
collected text reaches a language model it is:

1. normalised (NFKC) and stripped of control / zero-width / bidi characters,
2. truncated,
3. scanned for prompt-injection indicators (flagged, and neutralised by
   replacing the trigger phrase),
4. wrapped in a per-request random-nonce data envelope that the system prompt
   tells the model to treat as inert data.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass, field

_INVISIBLE = re.compile(
    "[\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2064\\u2066-\\u206f\\ufeff\\u00ad\\U000e0000-\\U000e007f]"
)

INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "override_instructions",
        re.compile(
            r"(?i)\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your|system)\b.{0,40}"
            r"\b(instruction|prompt|rule|direction|message)s?"
        ),
    ),
    ("role_reassignment", re.compile(r"(?i)\b(you are now|act as|pretend to be|from now on,? you)\b")),
    ("system_prompt_reference", re.compile(r"(?i)\b(system prompt|developer message|hidden instructions?)\b")),
    (
        "fake_role_tag",
        re.compile(
            r"(?i)(<\s*/?\s*(system|assistant|user|instructions?|(?:untrusted_)?data)[^>]*>|\[/?(INST|SYS)\]|\b(?:system|assistant)\s*:)"
        ),
    ),
    (
        "tool_or_exfil",
        re.compile(
            r"(?i)\b(call the|use the|invoke)\b.{0,30}\b(tool|function|api)\b|\bsend (it|this|"
            r"the data) to\b|https?://\S+\?\S*(token|key|secret)="
        ),
    ),
    (
        "verdict_manipulation",
        re.compile(r"(?i)\b(mark|classify|report|treat)\b.{0,40}\b(as )?(verified|confirmed|trusted|true|fact)\b"),
    ),
    ("output_format_hijack", re.compile(r"(?i)\b(respond|reply|answer|output) (only )?with\b")),
]


@dataclass
class SanitizedText:
    text: str
    flags: list[str] = field(default_factory=list)
    truncated: bool = False


def sanitize_untrusted(text: str | None, max_len: int = 600) -> SanitizedText:
    if not text:
        return SanitizedText(text="")
    value = unicodedata.normalize("NFKC", str(text))
    value = _INVISIBLE.sub("", value)
    value = "".join(ch if ch in "\n\t" or unicodedata.category(ch)[0] != "C" else " " for ch in value)
    value = re.sub(r"[ \t]+", " ", value).strip()
    flags: list[str] = []
    for label, pattern in INJECTION_PATTERNS:
        if pattern.search(value):
            flags.append(label)
            value = pattern.sub(f"[neutralised:{label}]", value)
    truncated = len(value) > max_len
    if truncated:
        value = value[:max_len] + "…"
    return SanitizedText(text=value, flags=flags, truncated=truncated)


def new_envelope_nonce() -> str:
    return secrets.token_hex(8)


def wrap_data(payload_json: str, nonce: str) -> str:
    # The closing tag cannot be forged by content because it contains a random nonce and all
    # angle brackets in collected content are escaped by the JSON serialiser below.
    return f'<untrusted_data id="{nonce}">\n{payload_json}\n</untrusted_data id="{nonce}">'


def escape_for_envelope(text: str) -> str:
    return text.replace("<", "\\u003c").replace(">", "\\u003e")
