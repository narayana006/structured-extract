import pytest

from structured_extract import JSONParseError, parse_json


def test_valid_json_needs_no_repairs():
    assert parse_json('{"a": [1, 2.5, null, true], "b": "x"}') == (
        {"a": [1, 2.5, None, True], "b": "x"},
        [],
    )
    assert parse_json("  [1, 2]\n") == ([1, 2], [])


def test_code_fence_and_surrounding_prose():
    text = 'Here it is:\n```json\n{"a": 1}\n```\nHope that helps!'
    value, repairs = parse_json(text)
    assert value == {"a": 1}
    assert repairs == ["removed a Markdown code fence"]


def test_prose_without_fence():
    value, repairs = parse_json('The result is {"a": {"b": [1, 2]}} as requested.')
    assert value == {"a": {"b": [1, 2]}}
    assert repairs == ["ignored text around the JSON"]


def test_outer_object_wins_over_nested_valid_objects():
    text = '{"items": [{"x": 1}, {"x": 2},], "n": 2}'
    value, repairs = parse_json(text)
    assert value == {"items": [{"x": 1}, {"x": 2}], "n": 2}
    assert repairs == ["removed a trailing comma"]


@pytest.mark.parametrize(
    "text, expected, repair",
    [
        ('{"a": 1,}', {"a": 1}, "removed a trailing comma"),
        ("[1, 2, ]", [1, 2], "removed a trailing comma"),
        ("{'a': 'it''s'}".replace("''", "\\'"), {"a": "it's"}, "converted non-standard quotes to double quotes"),
        ('{a: 1, b_c: "x"}', {"a": 1, "b_c": "x"}, "quoted an unquoted key"),
        ('{"a": True, "b": None}', {"a": True, "b": None}, "replaced True with a JSON literal"),
        ('{"a": 1 "b": 2}', {"a": 1, "b": 2}, "inserted a missing comma"),
        ('{"a": 1, // note\n "b": 2}', {"a": 1, "b": 2}, "removed comment"),
        ('{"a": /* x */ 1}', {"a": 1}, "removed comment"),
        ('{"a": "line one\nline two"}', {"a": "line one\nline two"}, "escaped a raw line break inside a string"),
        ('{"a": hello world, "b": 2}', {"a": "hello world", "b": 2}, "quoted an unquoted string"),
        ('{"a": +5, "b": .5}', {"a": 5, "b": 0.5}, "normalised a number"),
        ("{“a”: “b”}", {"a": "b"}, "converted non-standard quotes to double quotes"),
    ],
)
def test_repairs(text, expected, repair):
    value, repairs = parse_json(text)
    assert value == expected
    assert repair in repairs


@pytest.mark.parametrize(
    "text, expected",
    [
        ('{"a": [1, 2', {"a": [1, 2]}),
        ('{"a": {"b": "unfinished', {"a": {"b": "unfinished"}}),
        ('{"a": 1, "b"', {"a": 1}),
        ('{"a": 1, "b":', {"a": 1, "b": None}),
        ('[{"a": 1}, {"a": 2', [{"a": 1}, {"a": 2}]),
    ],
)
def test_truncated_output_is_closed(text, expected):
    value, repairs = parse_json(text)
    assert value == expected
    assert any("unterminated" in repair or "missing value" in repair for repair in repairs)


def test_escapes_survive_lenient_parsing():
    value, _ = parse_json('{"a": "tab\\there \\u00e9 \\"q\\"",}')
    assert value == {"a": 'tab\there é "q"'}


def test_bracketed_aside_before_the_object_is_skipped():
    value, repairs = parse_json('As noted [1], the answer is {"a": 1}')
    assert value == {"a": 1}
    assert "ignored text around the JSON" in repairs


def test_top_level_array_of_objects():
    value, _ = parse_json("Result: [{'a': 1}, {'a': 2}]")
    assert value == [{"a": 1}, {"a": 2}]


@pytest.mark.parametrize("text", ["", "no json here", "42", '"just a string"'])
def test_no_json(text):
    with pytest.raises(JSONParseError):
        parse_json(text)


def test_mismatched_brackets_raise():
    with pytest.raises(JSONParseError):
        parse_json('{"a": [1, 2}')


def test_non_string_input():
    with pytest.raises(JSONParseError):
        parse_json(None)
