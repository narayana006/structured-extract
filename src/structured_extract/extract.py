"""The validate-and-repair loop around a user-supplied ``complete`` callable."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .jsonrepair import JSONParseError, parse_json
from .schema import Issue, build_instance, coerce, to_json_schema, validate
from .spans import Span, find_spans

Complete = Callable[[str], str]


@dataclass
class Attempt:
    """One call to the model and what was wrong with its answer."""

    prompt: str
    response: str
    errors: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class Extraction:
    """A validated result.

    ``data`` is plain JSON data (dicts, lists, strings, numbers). ``value``
    is the same data as an instance of your dataclass or Pydantic model, or
    the dict itself for a JSON Schema. ``spans`` maps each string or number
    field to where it was found in the source text, or None if it was not.
    ``repairs`` lists the fixes applied to the accepted answer.
    """

    data: Any
    value: Any
    spans: dict[str, Span | None]
    attempts: list[Attempt]
    repairs: list[str]

    @property
    def ungrounded(self) -> list[str]:
        """Paths of extracted values that do not appear in the source."""
        return [path for path, span in self.spans.items() if span is None]


class ExtractionError(Exception):
    """No valid result after the allowed number of attempts."""

    def __init__(self, message: str, attempts: list[Attempt]) -> None:
        super().__init__(message)
        self.attempts = attempts


def build_prompt(schema: Any, text: str, instructions: str = "") -> str:
    """The prompt sent on the first attempt."""
    schema_json = json.dumps(to_json_schema(schema), indent=2, ensure_ascii=False)
    parts = [
        "Extract structured data from the document below.",
        "Reply with one JSON value that conforms to the JSON Schema. "
        "Use only information stated in the document, copy values as they are "
        "written, and reply with JSON only: no explanation, no Markdown.",
    ]
    if instructions:
        parts.append(instructions.strip())
    parts.append(f"JSON Schema:\n{schema_json}")
    parts.append(f"Document:\n<<<\n{text}\n>>>")
    return "\n\n".join(parts)


def _repair_prompt(first_prompt: str, response: str, errors: list[str]) -> str:
    bullet_list = "\n".join(f"- {error}" for error in errors)
    return (
        f"{first_prompt}\n\n"
        f"Your previous reply was:\n<<<\n{response}\n>>>\n\n"
        f"It was rejected for these reasons:\n{bullet_list}\n\n"
        "Reply again with the corrected JSON only."
    )


def check_output(
    schema: Any,
    response: str,
    source: str | None = None,
    *,
    coerce_types: bool = True,
    require_grounding: bool = False,
) -> tuple[Any, Any, list[str], list[str], dict[str, Span | None]]:
    """Parse, repair and validate one model reply without calling a model.

    Returns ``(data, value, errors, repairs, spans)``. ``errors`` is empty
    when the reply is acceptable. ``spans`` is empty when no ``source`` is
    given.
    """
    json_schema = to_json_schema(schema)
    try:
        data, repairs = parse_json(response)
    except JSONParseError as exc:
        return None, None, [f"reply is not JSON: {exc}"], [], {}
    if coerce_types:
        data, notes = coerce(data, json_schema)
        repairs = repairs + notes
    issues: list[Issue] = validate(data, json_schema)
    value = None
    if not issues:
        value, issues = build_instance(schema, data)
    spans = find_spans(data, source) if source is not None else {}
    errors = [str(issue) for issue in issues]
    if require_grounding and not errors:
        errors = [
            f"{path}: value {_leaf(data, path)!r} does not appear in the document"
            for path, span in spans.items()
            if span is None
        ]
    return data, value, errors, repairs, spans


def _leaf(data: Any, path: str) -> Any:
    node = data
    for part in path.replace("]", "").replace("[", ".").split("."):
        if part == "":
            continue
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def extract(
    schema: Any,
    text: str,
    complete: Complete,
    *,
    max_retries: int = 2,
    instructions: str = "",
    coerce_types: bool = True,
    require_grounding: bool = False,
) -> Extraction:
    """Extract data matching ``schema`` from ``text``.

    ``schema`` is a JSON Schema dict, a dataclass or a Pydantic v2 model
    class. ``complete`` is any function that takes a prompt string and
    returns the model's reply as a string; this library never talks to a
    model provider itself.

    The reply is parsed (with JSON repair), coerced and validated. If it
    fails, the errors are sent back to ``complete`` for another try, at most
    ``max_retries`` times, so ``complete`` is called at most
    ``max_retries + 1`` times. With ``require_grounding=True`` a string or
    number that cannot be found in ``text`` also counts as an error.

    Raises :class:`ExtractionError` (carrying every attempt) if no reply
    validates.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be 0 or greater")
    first_prompt = build_prompt(schema, text, instructions)
    prompt = first_prompt
    attempts: list[Attempt] = []
    for _ in range(max_retries + 1):
        response = complete(prompt)
        if not isinstance(response, str):
            raise TypeError(
                f"complete() must return a string, got {type(response).__name__}"
            )
        data, value, errors, repairs, spans = check_output(
            schema,
            response,
            text,
            coerce_types=coerce_types,
            require_grounding=require_grounding,
        )
        attempts.append(Attempt(prompt, response, errors, repairs))
        if not errors:
            return Extraction(data, value, spans, attempts, repairs)
        prompt = _repair_prompt(first_prompt, response, errors)
    last = attempts[-1].errors
    raise ExtractionError(
        f"no valid result after {len(attempts)} attempt(s); last errors: " + "; ".join(last),
        attempts,
    )


def extract_many(
    schema: Any,
    texts: Iterable[str],
    complete: Complete,
    **options: Any,
) -> list[Extraction | ExtractionError]:
    """Run :func:`extract` over several documents, one after another.

    A document that fails does not stop the batch: its slot in the returned
    list holds the :class:`ExtractionError` instead of an Extraction.
    """
    results: list[Extraction | ExtractionError] = []
    for text in texts:
        try:
            results.append(extract(schema, text, complete, **options))
        except ExtractionError as exc:
            results.append(exc)
    return results
