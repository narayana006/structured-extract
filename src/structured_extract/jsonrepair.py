"""Pull a JSON value out of model output, repairing common damage.

Handles the usual ways a model's "JSON" is not JSON: prose before or after
it, Markdown code fences, single-quoted or unquoted keys and strings,
trailing commas, missing commas, comments, Python literals (``True``,
``None``), raw line breaks inside strings, and output that was cut off before
the closing brackets.
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\n(.*?)(?:```|\Z)", re.DOTALL)
_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_BAREWORD_RE = re.compile(r"[^\s,:\[\]{}\"']+")
_LITERALS = {
    "true": True, "false": False, "null": None,
    "True": True, "False": False, "None": None,
    "undefined": None, "NaN": None,
}
_QUOTES = {'"': '"', "'": "'", "“": "”", "‘": "’"}
_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t", "'": "'"}


class JSONParseError(ValueError):
    """No JSON value could be recovered from the text."""


class _LenientParser:
    def __init__(self, text: str, start: int) -> None:
        self.text = text
        self.pos = start
        self.repairs: list[str] = []

    def note(self, message: str) -> None:
        if message not in self.repairs:
            self.repairs.append(message)

    def skip_space(self) -> None:
        text = self.text
        while self.pos < len(text):
            if text[self.pos].isspace():
                self.pos += 1
            elif text.startswith("//", self.pos):
                end = text.find("\n", self.pos)
                self.pos = len(text) if end == -1 else end
                self.note("removed comment")
            elif text.startswith("/*", self.pos):
                end = text.find("*/", self.pos + 2)
                self.pos = len(text) if end == -1 else end + 2
                self.note("removed comment")
            else:
                break

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def value(self) -> Any:
        self.skip_space()
        ch = self.peek()
        if ch == "":
            self.note("filled in a missing value with null")
            return None
        if ch == "{":
            return self.object()
        if ch == "[":
            return self.array()
        if ch in _QUOTES:
            return self.string()
        match = _NUMBER_RE.match(self.text, self.pos)
        if match and not _BAREWORD_RE.match(self.text, match.end()):
            return self.number(match)
        return self.bareword()

    def number(self, match: "re.Match[str]") -> Any:
        raw = match.group(0)
        self.pos = match.end()
        try:
            return json.loads(raw)
        except ValueError:
            self.note("normalised a number")
            cleaned = raw.lstrip("+")
            value = float(cleaned)
            is_integer = re.fullmatch(r"-?\d+\.?", cleaned) is not None
            return int(value) if is_integer else value

    def bareword(self) -> Any:
        match = _BAREWORD_RE.match(self.text, self.pos)
        if match is None:
            raise JSONParseError(
                f"unexpected character {self.peek()!r} at position {self.pos}"
            )
        word = match.group(0)
        self.pos = match.end()
        if word in _LITERALS:
            if word not in ("true", "false", "null"):
                self.note(f"replaced {word} with a JSON literal")
            return _LITERALS[word]
        # an unquoted string value: take the rest up to the next delimiter
        end = self.pos
        while end < len(self.text) and self.text[end] not in ",}]\n":
            end += 1
        word = (word + self.text[self.pos : end]).strip()
        self.pos = end
        self.note("quoted an unquoted string")
        return word

    def string(self) -> str:
        opening = self.text[self.pos]
        closing = _QUOTES[opening]
        if opening != '"':
            self.note("converted non-standard quotes to double quotes")
        self.pos += 1
        out: list[str] = []
        text = self.text
        while True:
            if self.pos >= len(text):
                self.note("closed an unterminated string")
                break
            ch = text[self.pos]
            if ch == closing:
                self.pos += 1
                break
            if ch == "\\" and self.pos + 1 < len(text):
                nxt = text[self.pos + 1]
                if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", text[self.pos + 2 : self.pos + 6]):
                    out.append(chr(int(text[self.pos + 2 : self.pos + 6], 16)))
                    self.pos += 6
                    continue
                if nxt in _ESCAPES:
                    out.append(_ESCAPES[nxt])
                else:
                    out.append(nxt)
                    self.note("dropped an invalid escape")
                self.pos += 2
                continue
            if ch in "\n\r":
                self.note("escaped a raw line break inside a string")
            out.append(ch)
            self.pos += 1
        return "".join(out)

    def key(self) -> str:
        if self.peek() in _QUOTES:
            return self.string()
        match = _BAREWORD_RE.match(self.text, self.pos)
        if match is None:
            raise JSONParseError(f"expected an object key at position {self.pos}")
        self.pos = match.end()
        self.note("quoted an unquoted key")
        return match.group(0)

    def object(self) -> dict:
        self.pos += 1  # {
        result: dict[str, Any] = {}
        while True:
            self.skip_space()
            ch = self.peek()
            if ch == "":
                self.note("closed an unterminated object")
                return result
            if ch == "}":
                self.pos += 1
                return result
            if ch == ",":
                self.pos += 1
                continue
            key = self.key()
            self.skip_space()
            if self.peek() in (":", "="):
                if self.peek() == "=":
                    self.note("replaced = with :")
                self.pos += 1
            elif self.peek() == "":
                self.note("closed an unterminated object")
                return result  # a dangling key from truncated output is dropped
            else:
                self.note("inserted a missing colon")
            result[key] = self.value()
            self.skip_space()
            ch = self.peek()
            if ch == ",":
                self.pos += 1
                self.skip_space()
                if self.peek() == "}":
                    self.note("removed a trailing comma")
            elif ch not in ("}", ""):
                if ch == "]":
                    raise JSONParseError(f"mismatched ] at position {self.pos}")
                self.note("inserted a missing comma")

    def array(self) -> list:
        self.pos += 1  # [
        result: list[Any] = []
        while True:
            self.skip_space()
            ch = self.peek()
            if ch == "":
                self.note("closed an unterminated array")
                return result
            if ch == "]":
                self.pos += 1
                return result
            if ch == ",":
                self.pos += 1
                continue
            if ch == "}":
                raise JSONParseError(f"mismatched }} at position {self.pos}")
            result.append(self.value())
            self.skip_space()
            ch = self.peek()
            if ch == ",":
                self.pos += 1
                self.skip_space()
                if self.peek() == "]":
                    self.note("removed a trailing comma")
            elif ch not in ("]", ""):
                self.note("inserted a missing comma")


def parse_json(text: str) -> tuple[Any, list[str]]:
    """Return ``(value, repairs)`` for the first JSON object or array in ``text``.

    ``repairs`` lists, in plain words, everything that had to be fixed; it is
    empty when the text was valid JSON already. Raises :class:`JSONParseError`
    when there is no object or array to recover.
    """
    if not isinstance(text, str):
        raise JSONParseError(f"expected text, got {type(text).__name__}")
    try:
        value = json.loads(text)
        if isinstance(value, (dict, list)):
            return value, []
    except ValueError:
        pass

    repairs: list[str] = []
    body = text
    fenced = _FENCE_RE.search(text)
    if fenced and re.search(r"[{\[]", fenced.group(1)):
        body = fenced.group(1)
        repairs.append("removed a Markdown code fence")

    start = _first_bracket(body, 0)
    if start == -1:
        raise JSONParseError("no JSON object or array found in the text")
    value, end, notes = _parse_at(body, start)
    if isinstance(value, list) and not any(isinstance(item, (dict, list)) for item in value):
        # a short bracketed aside such as "[1]" or "[sic]" before the real object
        brace = body.find("{", end)
        if brace != -1:
            start = brace
            value, end, notes = _parse_at(body, start)
    if body[:start].strip() or body[end:].strip():
        repairs.append("ignored text around the JSON")
    return value, repairs + notes


def _first_bracket(text: str, start: int) -> int:
    match = re.compile(r"[{\[]").search(text, start)
    return match.start() if match else -1


def _parse_at(text: str, start: int) -> tuple[Any, int, list[str]]:
    """Parse the value starting at ``start``: strictly if possible, else leniently."""
    try:
        value, end = json.JSONDecoder().raw_decode(text, start)
        return value, end, []
    except ValueError:
        parser = _LenientParser(text, start)
        value = parser.value()
        return value, parser.pos, parser.repairs
