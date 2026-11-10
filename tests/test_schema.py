import datetime
from dataclasses import dataclass, field
from typing import Literal, Optional

import pytest

from structured_extract import coerce, to_json_schema, validate
from structured_extract.schema import build_instance

PERSON = {
    "type": "object",
    "required": ["name", "age"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "age": {"type": "integer", "minimum": 0, "maximum": 150},
        "email": {"type": ["string", "null"], "format": "email"},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
        "role": {"enum": ["admin", "user"]},
    },
}


def messages(value, schema):
    return [str(issue) for issue in validate(value, schema)]


def test_valid_document():
    assert validate({"name": "Ada", "age": 36, "email": None, "tags": ["x"], "role": "user"}, PERSON) == []


def test_errors_carry_paths():
    doc = {"name": "", "age": 200, "email": "nope", "tags": ["a", 2, "c"], "role": "root", "x": 1}
    assert messages(doc, PERSON) == [
        "name: must be at least 1 characters",
        "age: must be <= 150, got 200",
        "email: is not a valid email: 'nope'",
        "tags: must have at most 2 items",
        "tags[1]: expected string, got integer",
        "role: must be one of 'admin', 'user'; got 'root'",
        "x: unexpected field",
    ]


def test_missing_required_and_wrong_root_type():
    assert messages({"name": "Ada"}, PERSON) == ["age: required field is missing"]
    assert messages([], PERSON) == ["(root): expected object, got array"]


@pytest.mark.parametrize(
    "value, schema, ok",
    [
        (True, {"type": "integer"}, False),  # bool is not a number
        (3.0, {"type": "integer"}, True),
        (3.5, {"type": "integer"}, False),
        (3, {"type": "number"}, True),
        (None, {"type": ["string", "null"]}, True),
        ("2024-02-30", {"type": "string", "format": "date"}, False),
        ("2024-02-29", {"type": "string", "format": "date"}, True),
        ("2024-02-29T10:00:00Z", {"type": "string", "format": "date-time"}, True),
        ("AB-12", {"type": "string", "pattern": r"^[A-Z]{2}-\d+$"}, True),
        ("ab-12", {"type": "string", "pattern": r"^[A-Z]{2}-\d+$"}, False),
        (5, {"exclusiveMinimum": 5}, False),
        (5, {"const": 5}, True),
        ("x", {"anyOf": [{"type": "integer"}, {"type": "string"}]}, True),
        ([], {"anyOf": [{"type": "integer"}, {"type": "string"}]}, False),
        (4, {"oneOf": [{"type": "integer"}, {"minimum": 3}]}, False),
        (4, {"allOf": [{"type": "integer"}, {"minimum": 5}]}, False),
        ({"a": 1}, {"type": "object", "additionalProperties": {"type": "string"}}, False),
        ("anything", {}, True),
    ],
)
def test_keywords(value, schema, ok):
    assert (validate(value, schema) == []) is ok


def test_local_refs():
    schema = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"$ref": "#/$defs/Item"}}},
        "$defs": {"Item": {"type": "object", "required": ["sku"], "properties": {"sku": {"type": "string"}}}},
    }
    assert validate({"items": [{"sku": "a"}]}, schema) == []
    assert messages({"items": [{"sku": "a"}, {}]}, schema) == ["items[1].sku: required field is missing"]
    with pytest.raises(ValueError):
        validate({}, {"$ref": "http://example.com/schema.json"})
    with pytest.raises(ValueError):
        validate({}, {"$ref": "#/$defs/Missing"})


def test_coerce_fixes_near_misses():
    doc = {"name": "  Ada ", "age": "36", "tags": [1, "b"], "extra": "1"}
    fixed, notes = coerce(doc, PERSON)
    assert fixed == {"name": "Ada", "age": 36, "tags": ["1", "b"], "extra": "1"}
    assert notes == [
        "name: stripped surrounding whitespace",
        "age: converted string '36' to number",
        "tags[0]: converted number 1 to string",
    ]
    assert doc["age"] == "36"  # the input is not modified


@pytest.mark.parametrize(
    "value, schema, expected",
    [
        ("1,250.00", {"type": "number"}, 1250.0),
        ("1,250", {"type": "integer"}, 1250),
        ("12", {"type": "number"}, 12),
        ("12.5", {"type": "integer"}, "12.5"),  # lossy, so left for validation to report
        ("12 units", {"type": "number"}, "12 units"),
        ("TRUE", {"type": "boolean"}, True),
        ("yes", {"type": "boolean"}, "yes"),
        (7.0, {"type": "integer"}, 7),
        ("42", {"type": ["string", "integer"]}, "42"),  # already an allowed type
        ("42", {"anyOf": [{"type": "integer"}, {"type": "null"}]}, 42),
        (True, {"type": "string"}, True),
        ("n/a", {"type": ["number", "null"]}, None),
        ("n/a", {"type": ["string", "null"]}, "n/a"),  # a string is allowed, so it stays
    ],
)
def test_coerce_cases(value, schema, expected):
    result, _ = coerce(value, schema)
    assert result == expected and type(result) is type(expected)


@dataclass
class Address:
    city: str
    postcode: Optional[str] = None


@dataclass
class Customer:
    name: str = field(metadata={"description": "Full legal name"})
    address: Address
    tier: Literal["free", "pro"]
    signup: datetime.date
    seats: int = 1
    notes: list[str] = field(default_factory=list)


def test_dataclass_to_schema():
    schema = to_json_schema(Customer)
    assert schema["required"] == ["name", "address", "tier", "signup"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["name"] == {"type": "string", "description": "Full legal name"}
    assert schema["properties"]["tier"] == {"enum": ["free", "pro"]}
    assert schema["properties"]["signup"] == {"type": "string", "format": "date"}
    assert schema["properties"]["notes"] == {"type": "array", "items": {"type": "string"}}
    assert schema["properties"]["address"]["properties"]["postcode"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}]
    }


def test_dataclass_instance_is_built_recursively():
    data = {"name": "Ada", "address": {"city": "London"}, "tier": "pro", "signup": "2024-01-31"}
    assert validate(data, to_json_schema(Customer)) == []
    customer, issues = build_instance(Customer, data)
    assert issues == []
    assert customer == Customer("Ada", Address("London"), "pro", datetime.date(2024, 1, 31))


def test_to_json_schema_rejects_other_things():
    with pytest.raises(TypeError):
        to_json_schema("not a schema")
    with pytest.raises(TypeError):
        to_json_schema(int)
