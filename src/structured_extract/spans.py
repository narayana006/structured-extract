"""Locate where each extracted value appears in the source text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# A numeral that is not a fragment of a longer number, a date or an identifier
# such as 2024-04-13 or INV-0042.
_NUMBER_TOKEN = re.compile(
    r"(?<![\w.,])(?<!\d[-/])(?<![A-Za-z]-)\d+(?:,\d{3})*(?:\.\d+)?(?![-/]?\d)(?![A-Za-z_])"
)


@dataclass(frozen=True)
class Span:
    """A half-open character range ``[start, end)`` in the source text."""

    start: int
    end: int
    text: str


def _span(source: str, start: int, end: int) -> Span:
    return Span(start, end, source[start:end])


def _find_string(value: str, source: str) -> Span | None:
    needle = value.strip()
    if not needle:
        return None
    index = source.find(needle)
    if index != -1:
        return _span(source, index, index + len(needle))
    # same words, any case, any whitespace or line breaks between them
    pattern = r"\s+".join(re.escape(word) for word in needle.split())
    match = re.search(pattern, source, re.IGNORECASE)
    if match:
        return _span(source, match.start(), match.end())
    return None


def _find_number(value: float, source: str, near: int | None = None) -> Span | None:
    target = abs(value)
    best: Span | None = None
    for match in _NUMBER_TOKEN.finditer(source):
        try:
            number = float(match.group(0).replace(",", ""))
        except ValueError:
            continue
        if number != target:
            continue
        start = match.start()
        if value < 0:
            if start == 0 or source[start - 1] not in "-\u2212":
                continue
            start -= 1
        candidate = _span(source, start, match.end())
        if near is None:
            return candidate
        if best is None or abs(candidate.start - near) < abs(best.start - near):
            best = candidate
    return best


def find_span(value: Any, source: str, near: int | None = None) -> Span | None:
    """Find a string or number in ``source``; None if it is not there.

    Strings match exactly first, then ignoring case and whitespace
    differences. Numbers match any numeral with the same value, so ``1250.0``
    finds ``1,250.00``; digits inside dates and identifiers are not counted.
    If a number occurs several times, the first occurrence is returned, or
    the one closest to character offset ``near`` when that is given.
    Booleans, nulls and containers have no span.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        return _find_string(value, source)
    if isinstance(value, (int, float)):
        return _find_number(value, source, near)
    return None


def find_spans(data: Any, source: str) -> dict[str, Span | None]:
    """Map every string or number leaf in ``data`` to its span in ``source``.

    Keys are paths such as ``vendor`` or ``line_items[0].amount``. A value of
    None means the extracted value does not appear in the source, which is
    worth a second look: it may be inferred, reformatted or made up. When a
    number occurs more than once, the occurrence closest to a string field of
    the same object is chosen.
    """
    spans: dict[str, Span | None] = {}

    def visit(node: Any, path: str, near: int | None) -> None:
        if isinstance(node, dict):
            # strings first: the first one found anchors this object's numbers
            anchor = near
            for key, item in node.items():
                if isinstance(item, str):
                    span = find_span(item, source)
                    if span is not None:
                        anchor = span.start
                        break
            for key, item in node.items():
                visit(item, f"{path}.{key}" if path else str(key), anchor)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                visit(item, f"{path}[{index}]", near)
        elif isinstance(node, bool) or node is None:
            return
        elif isinstance(node, (str, int, float)):
            spans[path] = find_span(node, source, near)

    visit(data, "", None)
    return spans
