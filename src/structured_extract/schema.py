"""JSON Schema validation and safe coercion, plus schema adapters.

Implements the subset of JSON Schema that extraction schemas use in
practice: ``type``, ``properties``, ``required``, ``additionalProperties``,
``items``, ``enum``, ``const``, numeric and length bounds, ``pattern``,
``format`` (``date``, ``date-time``, ``email``), ``anyOf`` / ``oneOf`` /
``allOf`` and local ``$ref``. Unknown keywords are ignored.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
import types
import typing
from dataclasses import dataclass
from typing import Any, Union

_NUMERIC_STRING = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\Z")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")


@dataclass(frozen=True)
class Issue:
    """One validation problem. ``path`` looks like ``items[0].price``."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '(root)'}: {self.message}"


def _join(path: str, key: Union[str, int]) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


def _resolve(schema: Any, root: dict) -> Any:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#"):
            raise ValueError(f"only local $ref is supported, got {ref!r}")
        node: Any = root
        for part in ref[1:].split("/"):
            if part:
                part = part.replace("~1", "/").replace("~0", "~")
                try:
                    node = node[part]
                except (KeyError, TypeError):
                    raise ValueError(f"unresolvable $ref {ref!r}") from None
        schema = node
        seen += 1
        if seen > 50:
            raise ValueError(f"circular $ref {ref!r}")
    return schema


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_type(value: Any, name: str) -> bool:
    actual = _type_name(value)
    if name == "number":
        return actual in ("integer", "number")
    if name == "integer":
        return actual == "integer" or (actual == "number" and float(value).is_integer())
    return actual == name


def _types(schema: dict) -> list[str]:
    declared = schema.get("type")
    if declared is None:
        return []
    return [declared] if isinstance(declared, str) else list(declared)


def _check_format(value: str, fmt: str) -> bool:
    try:
        if fmt == "date":
            datetime.date.fromisoformat(value)
            return len(value) == 10
        if fmt == "date-time":
            datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return "T" in value or " " in value
    except ValueError:
        return False
    if fmt == "email":
        return _EMAIL.match(value) is not None
    return True


def validate(value: Any, schema: dict, *, _root: dict | None = None, _path: str = "") -> list[Issue]:
    """Return every way ``value`` violates ``schema`` (empty list if valid)."""
    root = schema if _root is None else _root
    schema = _resolve(schema, root)
    if schema is True or schema == {}:
        return []
    if schema is False:
        return [Issue(_path, "no value is allowed here")]
    issues: list[Issue] = []
    path = _path

    types_ = _types(schema)
    if types_ and not any(_is_type(value, name) for name in types_):
        expected = " or ".join(types_)
        return [Issue(path, f"expected {expected}, got {_type_name(value)}")]

    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(repr(option) for option in schema["enum"])
        issues.append(Issue(path, f"must be one of {allowed}; got {value!r}"))
    if "const" in schema and value != schema["const"]:
        issues.append(Issue(path, f"must equal {schema['const']!r}"))

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            issues.append(Issue(path, f"must be >= {schema['minimum']}, got {value}"))
        if "maximum" in schema and value > schema["maximum"]:
            issues.append(Issue(path, f"must be <= {schema['maximum']}, got {value}"))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            issues.append(Issue(path, f"must be > {schema['exclusiveMinimum']}, got {value}"))
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            issues.append(Issue(path, f"must be < {schema['exclusiveMaximum']}, got {value}"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            issues.append(Issue(path, f"must be at least {schema['minLength']} characters"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            issues.append(Issue(path, f"must be at most {schema['maxLength']} characters"))
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            issues.append(Issue(path, f"does not match pattern {schema['pattern']}"))
        if "format" in schema and not _check_format(value, schema["format"]):
            issues.append(Issue(path, f"is not a valid {schema['format']}: {value!r}"))

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            issues.append(Issue(path, f"must have at least {schema['minItems']} items"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            issues.append(Issue(path, f"must have at most {schema['maxItems']} items"))
        if "items" in schema:
            for index, item in enumerate(value):
                issues += validate(item, schema["items"], _root=root, _path=_join(path, index))

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                issues.append(Issue(_join(path, name), "required field is missing"))
        additional = schema.get("additionalProperties", True)
        for name, item in value.items():
            if name in properties:
                issues += validate(item, properties[name], _root=root, _path=_join(path, name))
            elif additional is False:
                issues.append(Issue(_join(path, name), "unexpected field"))
            elif isinstance(additional, dict):
                issues += validate(item, additional, _root=root, _path=_join(path, name))

    for sub in schema.get("allOf", []):
        issues += validate(value, sub, _root=root, _path=path)
    for keyword in ("anyOf", "oneOf"):
        if keyword in schema:
            results = [validate(value, sub, _root=root, _path=path) for sub in schema[keyword]]
            passing = sum(1 for result in results if not result)
            if passing == 0:
                # report the branch that came closest
                issues += min(results, key=len)
            elif keyword == "oneOf" and passing > 1:
                issues.append(Issue(path, "matches more than one allowed alternative"))
    return issues


def coerce(value: Any, schema: dict, *, _root: dict | None = None, _path: str = "") -> tuple[Any, list[str]]:
    """Apply safe, lossless fixes so near-miss values pass validation.

    Converts numeric strings (``"1,250.00"``) to numbers and ``"true"`` /
    ``"false"`` to booleans where the schema asks for those types, turns
    whole floats into integers, numbers into strings where a string is
    required, and strips surrounding whitespace from strings. Returns the new
    value and a description of each change.
    """
    root = schema if _root is None else _root
    schema = _resolve(schema, root)
    if not isinstance(schema, dict):
        return value, []
    notes: list[str] = []
    where = _path or "(root)"

    for keyword in ("anyOf", "oneOf"):
        if keyword in schema and not any(
            not validate(value, sub, _root=root) for sub in schema[keyword]
        ):
            for sub in schema[keyword]:
                candidate, sub_notes = coerce(value, sub, _root=root, _path=_path)
                if sub_notes and not validate(candidate, sub, _root=root):
                    return candidate, sub_notes

    types_ = _types(schema)
    if isinstance(value, str):
        stripped = value.strip()
        wants_number = "number" in types_ or "integer" in types_
        if wants_number and "string" not in types_ and _NUMERIC_STRING.match(stripped):
            number = float(stripped.replace(",", ""))
            if number.is_integer() and ("integer" in types_ or "." not in stripped):
                number = int(number)
            if not (isinstance(number, float) and "number" not in types_):
                notes.append(f"{where}: converted string {value!r} to number")
                value = number
        elif "boolean" in types_ and "string" not in types_ and stripped.lower() in ("true", "false"):
            notes.append(f"{where}: converted string {value!r} to boolean")
            value = stripped.lower() == "true"
        elif "null" in types_ and "string" not in types_ and stripped.lower() in ("", "null", "none", "n/a"):
            notes.append(f"{where}: converted string {value!r} to null")
            value = None
        elif stripped != value and (not types_ or "string" in types_):
            notes.append(f"{where}: stripped surrounding whitespace")
            value = stripped
    elif isinstance(value, float) and value.is_integer() and "integer" in types_ and "number" not in types_:
        notes.append(f"{where}: converted {value!r} to integer")
        value = int(value)
    elif (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and types_
        and "string" in types_
        and not {"number", "integer"} & set(types_)
    ):
        notes.append(f"{where}: converted number {value!r} to string")
        value = str(value)

    if isinstance(value, list) and "items" in schema:
        items = []
        for index, item in enumerate(value):
            new, sub_notes = coerce(item, schema["items"], _root=root, _path=_join(_path, index))
            items.append(new)
            notes += sub_notes
        value = items
    elif isinstance(value, dict) and "properties" in schema:
        result = {}
        for name, item in value.items():
            if name in schema["properties"]:
                item, sub_notes = coerce(
                    item, schema["properties"][name], _root=root, _path=_join(_path, name)
                )
                notes += sub_notes
            result[name] = item
        value = result
    return value, notes


# --- adapters: dataclasses and Pydantic models -----------------------------

def _is_pydantic_model(schema: Any) -> bool:
    return isinstance(schema, type) and hasattr(schema, "model_json_schema") and hasattr(
        schema, "model_validate"
    )


def _annotation_schema(annotation: Any) -> dict:
    if annotation is Any:
        return {}
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is type(None):
        return {"type": "null"}
    if annotation is datetime.date:
        return {"type": "string", "format": "date"}
    if dataclasses.is_dataclass(annotation):
        return _dataclass_schema(annotation)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (list, tuple, set, frozenset):
        return {"type": "array", "items": _annotation_schema(args[0]) if args else {}}
    if origin is dict:
        return {"type": "object"}
    if origin is typing.Literal:
        return {"enum": list(args)}
    if origin is Union or origin is types.UnionType:
        return {"anyOf": [_annotation_schema(arg) for arg in args]}
    if annotation in (list, tuple):
        return {"type": "array"}
    if annotation is dict:
        return {"type": "object"}
    raise TypeError(f"cannot build a JSON Schema for annotation {annotation!r}")


def _dataclass_schema(cls: type) -> dict:
    hints = typing.get_type_hints(cls)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for field in dataclasses.fields(cls):
        prop = dict(_annotation_schema(hints[field.name]))
        if "description" in field.metadata:
            prop["description"] = field.metadata["description"]
        properties[field.name] = prop
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            required.append(field.name)
    schema: dict[str, Any] = {
        "type": "object",
        "title": cls.__name__,
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    return schema


def to_json_schema(schema: Any) -> dict:
    """Accept a JSON Schema dict, a dataclass or a Pydantic v2 model class."""
    if isinstance(schema, dict):
        return schema
    if _is_pydantic_model(schema):
        return schema.model_json_schema()
    if isinstance(schema, type) and dataclasses.is_dataclass(schema):
        return _dataclass_schema(schema)
    raise TypeError(
        "schema must be a JSON Schema dict, a dataclass or a Pydantic model class, "
        f"got {schema!r}"
    )


def _build_annotation(annotation: Any, data: Any) -> Any:
    if data is None:
        return None
    if dataclasses.is_dataclass(annotation) and isinstance(data, dict):
        hints = typing.get_type_hints(annotation)
        return annotation(**{k: _build_annotation(hints[k], v) for k, v in data.items()})
    if annotation is datetime.date and isinstance(data, str):
        return datetime.date.fromisoformat(data)
    if annotation is float and isinstance(data, int):
        return float(data)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (list, tuple, set, frozenset) and args and isinstance(data, list):
        return origin(_build_annotation(args[0], item) for item in data)
    if origin is Union or origin is types.UnionType:
        for arg in args:
            if arg is type(None):
                continue
            try:
                if not validate(data, _annotation_schema(arg)):
                    return _build_annotation(arg, data)
            except TypeError:
                continue
    return data


def build_instance(schema: Any, data: Any) -> tuple[Any, list[Issue]]:
    """Turn validated JSON data into the caller's type.

    Returns ``(instance, issues)``. For a dict schema the data is returned
    unchanged. A Pydantic model runs its own validators here, and any errors
    they raise come back as issues so the repair loop can report them.
    """
    if isinstance(schema, dict):
        return data, []
    if _is_pydantic_model(schema):
        try:
            return schema.model_validate(data), []
        except Exception as exc:  # pydantic.ValidationError, without importing pydantic
            errors = getattr(exc, "errors", None)
            if not callable(errors):
                raise
            issues = []
            for error in errors():
                path = ""
                for part in error.get("loc", ()):
                    path = _join(path, part)
                issues.append(Issue(path, str(error.get("msg", "invalid value"))))
            return None, issues
    return _build_annotation(schema, data), []
