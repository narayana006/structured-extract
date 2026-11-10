import json
from dataclasses import dataclass

import pytest

from structured_extract import ExtractionError, build_prompt, check_output, extract, extract_many

SCHEMA = {
    "type": "object",
    "required": ["name", "amount"],
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "amount": {"type": "number", "minimum": 0},
    },
}
TEXT = "Payment of 1,200.50 received from Acme Ltd on Monday."
GOOD = '{"name": "Acme Ltd", "amount": 1200.5}'


class FakeModel:
    """Returns scripted replies and records the prompts it was given."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_first_reply_valid():
    model = FakeModel(GOOD)
    result = extract(SCHEMA, TEXT, model)
    assert result.data == {"name": "Acme Ltd", "amount": 1200.5}
    assert result.value == result.data
    assert result.repairs == []
    assert len(result.attempts) == 1 and result.attempts[0].ok
    assert len(model.prompts) == 1


def test_prompt_contains_schema_document_and_instructions():
    prompt = build_prompt(SCHEMA, TEXT, instructions="Amounts are in GBP.")
    assert json.dumps(SCHEMA, indent=2) in prompt
    assert f"<<<\n{TEXT}\n>>>" in prompt
    assert "Amounts are in GBP." in prompt
    model = FakeModel(GOOD)
    extract(SCHEMA, TEXT, model, instructions="Amounts are in GBP.")
    assert model.prompts[0] == prompt


def test_messy_reply_is_repaired_without_a_retry():
    model = FakeModel("Sure:\n```json\n{'name': 'Acme Ltd', 'amount': '1,200.50',}\n```")
    result = extract(SCHEMA, TEXT, model)
    assert result.data == {"name": "Acme Ltd", "amount": 1200.5}
    assert len(model.prompts) == 1
    assert "removed a Markdown code fence" in result.repairs
    assert "amount: converted string '1,200.50' to number" in result.repairs


def test_invalid_reply_triggers_repair_prompt_with_errors():
    bad = '{"name": "Acme Ltd", "amount": -5, "note": "paid"}'
    model = FakeModel(bad, GOOD)
    result = extract(SCHEMA, TEXT, model)
    assert result.data["amount"] == 1200.5
    assert [a.ok for a in result.attempts] == [False, True]
    assert result.attempts[0].errors == ["amount: must be >= 0, got -5", "note: unexpected field"]
    retry_prompt = model.prompts[1]
    assert retry_prompt.startswith(model.prompts[0])
    assert bad in retry_prompt
    assert "- amount: must be >= 0, got -5" in retry_prompt
    assert "- note: unexpected field" in retry_prompt


def test_non_json_reply_is_retried():
    model = FakeModel("I cannot find an invoice.", GOOD)
    result = extract(SCHEMA, TEXT, model)
    assert result.attempts[0].errors[0].startswith("reply is not JSON")
    assert result.data["name"] == "Acme Ltd"


def test_retries_are_bounded():
    model = FakeModel("{}", "{}", "{}", GOOD)
    with pytest.raises(ExtractionError) as excinfo:
        extract(SCHEMA, TEXT, model, max_retries=2)
    assert len(model.prompts) == 3
    assert len(excinfo.value.attempts) == 3
    assert "no valid result after 3 attempt(s)" in str(excinfo.value)
    assert "name: required field is missing" in str(excinfo.value)


def test_zero_retries_and_negative_retries():
    model = FakeModel("{}", GOOD)
    with pytest.raises(ExtractionError):
        extract(SCHEMA, TEXT, model, max_retries=0)
    assert len(model.prompts) == 1
    with pytest.raises(ValueError):
        extract(SCHEMA, TEXT, model, max_retries=-1)


def test_coercion_can_be_turned_off():
    model = FakeModel('{"name": "Acme Ltd", "amount": "1200.5"}', GOOD)
    result = extract(SCHEMA, TEXT, model, coerce_types=False)
    assert result.attempts[0].errors == ["amount: expected number, got string"]


def test_spans_point_into_the_source():
    result = extract(SCHEMA, TEXT, FakeModel(GOOD))
    assert result.spans["name"].text == "Acme Ltd"
    assert result.spans["amount"].text == "1,200.50"
    assert TEXT[result.spans["amount"].start : result.spans["amount"].end] == "1,200.50"
    assert result.ungrounded == []


def test_ungrounded_values_are_reported():
    result = extract(SCHEMA, TEXT, FakeModel('{"name": "Acme Corporation", "amount": 1200.5}'))
    assert result.spans["name"] is None
    assert result.ungrounded == ["name"]


def test_require_grounding_sends_made_up_values_back():
    model = FakeModel('{"name": "Acme Corporation", "amount": 1200.5}', GOOD)
    result = extract(SCHEMA, TEXT, model, require_grounding=True)
    assert result.attempts[0].errors == [
        "name: value 'Acme Corporation' does not appear in the document"
    ]
    assert result.data["name"] == "Acme Ltd"


def test_complete_must_return_a_string():
    with pytest.raises(TypeError):
        extract(SCHEMA, TEXT, lambda prompt: {"name": "x"})


def test_check_output_without_a_model():
    data, value, errors, repairs, spans = check_output(SCHEMA, GOOD + " trailing words", TEXT)
    assert errors == [] and data == value
    assert repairs == ["ignored text around the JSON"]
    assert spans["name"].text == "Acme Ltd"
    assert check_output(SCHEMA, "nope")[2] == [
        "reply is not JSON: no JSON object or array found in the text"
    ]


@dataclass
class Payment:
    name: str
    amount: float


def test_dataclass_schema_returns_an_instance():
    result = extract(Payment, TEXT, FakeModel('{"name": "Acme Ltd", "amount": 1200}'))
    assert result.value == Payment("Acme Ltd", 1200.0)
    assert isinstance(result.value.amount, float)
    assert result.data == {"name": "Acme Ltd", "amount": 1200}


def test_extract_many_keeps_going_after_a_failure():
    model = FakeModel(GOOD, "{}", "{}", '{"name": "Zed", "amount": 3}')
    results = extract_many(SCHEMA, ["doc one", "doc two", "doc three"], model, max_retries=1)
    assert results[0].data["name"] == "Acme Ltd"
    assert isinstance(results[1], ExtractionError) and len(results[1].attempts) == 2
    assert results[2].data == {"name": "Zed", "amount": 3}


def test_pydantic_model_schema_and_validators():
    pydantic = pytest.importorskip("pydantic")

    class Line(pydantic.BaseModel):
        sku: str
        qty: int

    class Order(pydantic.BaseModel):
        customer: str
        lines: list[Line]
        coupon: str | None = None

        @pydantic.field_validator("customer")
        @classmethod
        def not_placeholder(cls, value):
            if value.lower() == "unknown":
                raise ValueError("customer must be a real name")
            return value

    text = "Acme Ltd ordered 3 of SKU-9."
    model = FakeModel(
        '{"customer": "Acme Ltd", "lines": [{"sku": "SKU-9"}]}',  # fails the JSON Schema ($ref)
        '{"customer": "unknown", "lines": [{"sku": "SKU-9", "qty": 3}]}',  # fails the validator
        '{"customer": "Acme Ltd", "lines": [{"sku": "SKU-9", "qty": "3"}]}',
    )
    result = extract(Order, text, model)
    assert isinstance(result.value, Order)
    assert result.value.lines[0].qty == 3 and result.value.coupon is None
    assert result.attempts[0].errors == ["lines[0].qty: required field is missing"]
    assert "customer must be a real name" in result.attempts[1].errors[0]
    assert result.attempts[1].errors[0].startswith("customer: ")
    assert result.spans["lines[0].sku"].text == "SKU-9"
