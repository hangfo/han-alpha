from __future__ import annotations

import re

_BLOCKED_PATTERNS = [
    r"ignore\s+(all|any|the)\s+(previous|prior|system)\s+instructions",
    r"reveal\s+(the\s+)?(system|developer)\s+prompt",
    r"send\s+(money|funds)",
    r"place\s+(an?\s+)?order",
    r"disable\s+(risk|safety|guardrail)",
    r"override\s+(risk|limits|policy)",
    r"api[_ -]?key",
    r"password",
    r"private[_ -]?key",
]


def sanitize_untrusted_text(text: str, max_length: int = 4000) -> str:
    clean = text.replace("\x00", " ").strip()[:max_length]
    for pattern in _BLOCKED_PATTERNS:
        clean = re.sub(pattern, "[BLOCKED_UNTRUSTED_INSTRUCTION]", clean, flags=re.IGNORECASE)
    return clean


def contains_prompt_injection(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _BLOCKED_PATTERNS)
