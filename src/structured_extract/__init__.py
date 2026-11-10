"""Schema-driven extraction with a validate-and-repair loop."""

from .extract import (
    Attempt,
    Extraction,
    ExtractionError,
    build_prompt,
    check_output,
    extract,
    extract_many,
)
from .jsonrepair import JSONParseError, parse_json
from .schema import Issue, coerce, to_json_schema, validate
from .spans import Span, find_span, find_spans

__all__ = [
    "Attempt",
    "Extraction",
    "ExtractionError",
    "Issue",
    "JSONParseError",
    "Span",
    "build_prompt",
    "check_output",
    "coerce",
    "extract",
    "extract_many",
    "find_span",
    "find_spans",
    "parse_json",
    "to_json_schema",
    "validate",
]

__version__ = "0.1.0"
