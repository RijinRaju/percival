"""Turning task arguments into something safe to ship to the panel.

Two rules: anything whose name looks sensitive is replaced, and everything
else is made JSON-friendly and size-capped. Positional args are matched to
parameter names through the signature so ``send(user, token)`` still gets its
token hidden.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping
from typing import Any

REDACTED = "[redacted]"

_SCALARS = (str, int, float, bool, type(None))


def is_sensitive(name: str, patterns: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(p.lower() in lowered for p in patterns)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"... [{len(text) - max_chars} more chars]"


def scrub(value: Any, patterns: Iterable[str], max_chars: int = 2_000, _depth: int = 0) -> Any:
    patterns = tuple(patterns)
    if _depth > 8:
        return "[too deep]"

    if isinstance(value, str):
        return _truncate(value, max_chars)
    if isinstance(value, _SCALARS):
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if is_sensitive(key_str, patterns):
                out[key_str] = REDACTED
            else:
                out[key_str] = scrub(item, patterns, max_chars, _depth + 1)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [scrub(item, patterns, max_chars, _depth + 1) for item in value]
    return _truncate(repr(value), max_chars)


def capture_args(
    func: Callable[..., Any] | None,
    args: Iterable[Any] | None,
    kwargs: Mapping[str, Any] | None,
    patterns: Iterable[str],
    max_chars: int = 2_000,
) -> dict[str, Any]:
    patterns = tuple(patterns)
    args = list(args or ())
    kwargs = dict(kwargs or {})

    names = _positional_names(func, len(args))
    clean_args = []
    for index, value in enumerate(args):
        name = names[index] if index < len(names) else None
        if name and is_sensitive(name, patterns):
            clean_args.append(REDACTED)
        else:
            clean_args.append(scrub(value, patterns, max_chars))

    return {
        "args": clean_args,
        "kwargs": scrub(kwargs, patterns, max_chars),
    }


def _positional_names(func: Callable[..., Any] | None, count: int) -> list[str]:
    if func is None or count == 0:
        return []
    try:
        params = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return []
    names = []
    for p in params:
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            names.append(p.name)
        elif p.kind is p.VAR_POSITIONAL:
            break
    return names
