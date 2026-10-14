"""Identifier tokenization shared by blocking, scoring and the merge guards."""

from __future__ import annotations

import re

_WORDS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")

#: Words that only say *what kind of thing* an identifier is ("BrakeController" and
#: "BrakeControllerSWC" are plausibly one item). Dropped for blocking keys only; they never
#: contribute to an automatic merge.
TYPE_NOISE = frozenset(
    {
        "swc",
        "component",
        "comp",
        "interface",
        "if",
        "itf",
        "port",
        "signal",
        "sig",
        "runnable",
        "function",
        "func",
        "the",
    }
)

#: Qualifiers whose swap makes two otherwise identical names *different* items
#: (``WheelSpeed_FL`` / ``WheelSpeed_FR``, ``Request`` / ``Response``).
OPPOSITE_QUALIFIERS: tuple[frozenset[str], ...] = tuple(
    frozenset(pair)
    for pair in (
        ("fl", "fr"),
        ("fl", "rl"),
        ("fl", "rr"),
        ("fr", "rl"),
        ("fr", "rr"),
        ("rl", "rr"),
        ("left", "right"),
        ("front", "rear"),
        ("front", "back"),
        ("in", "out"),
        ("input", "output"),
        ("tx", "rx"),
        ("request", "response"),
        ("req", "resp"),
        ("min", "max"),
        ("set", "get"),
        ("read", "write"),
        ("rd", "wr"),
        ("provided", "required"),
        ("send", "receive"),
        ("sender", "receiver"),
        ("master", "slave"),
        ("primary", "secondary"),
        ("start", "stop"),
        ("enable", "disable"),
        ("up", "down"),
        ("high", "low"),
        ("on", "off"),
    )
)


def tokenize(name: str) -> list[str]:
    """Split an identifier into lower-case word tokens (camelCase, snake_case, digits)."""
    tokens: list[str] = []
    for part in _SEPARATORS.split(name):
        tokens.extend(token.lower() for token in _WORDS.findall(part))
    return tokens


def core_tokens(name: str) -> list[str]:
    """Meaningful word tokens: no type noise, no pure numbers."""
    return [token for token in tokenize(name) if token not in TYPE_NOISE and not token.isdigit()]


def number_tokens(name: str) -> tuple[str, ...]:
    """The numeric tokens (version, index) of a name, in order: ``Port2_V3`` -> ('2', '3')."""
    return tuple(token for token in tokenize(name) if token.isdigit())


def acronym(name: str) -> str | None:
    """Initials of the core tokens (``Wheel Speed Sensor`` -> ``wss``), ``None`` if too short."""
    tokens = core_tokens(name)
    return "".join(token[0] for token in tokens) if len(tokens) >= 2 else None


def looks_like_acronym(name: str) -> bool:
    """Short all-capitals identifiers such as ``WSS`` or ``ECU``."""
    stripped = _SEPARATORS.sub("", name)
    return 2 <= len(stripped) <= 6 and stripped.isalpha() and stripped.isupper()


def opposite_qualifier(left: str, right: str) -> bool:
    """True when the names differ exactly by one qualifier and its opposite."""
    left_tokens, right_tokens = set(tokenize(left)), set(tokenize(right))
    only_left, only_right = left_tokens - right_tokens, right_tokens - left_tokens
    return any(pair & only_left and pair & only_right for pair in OPPOSITE_QUALIFIERS)
