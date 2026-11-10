from structured_extract import Span, find_span, find_spans

SOURCE = (
    "Order ORD-0042 placed 2024-04-13 by Maria  Lopez\n"
    "(maria@example.com). 4 widgets at 1,250.00 each, discount -15.5.\n"
    "Balance due: 4,984.50 EUR"
)


def text_of(value):
    span = find_span(value, SOURCE)
    return None if span is None else span.text


def test_exact_string():
    span = find_span("maria@example.com", SOURCE)
    assert span == Span(50, 67, "maria@example.com")
    assert SOURCE[span.start : span.end] == span.text


def test_string_ignores_case_and_whitespace():
    assert text_of("maria lopez") == "Maria  Lopez"
    assert text_of("Balance   due") == "Balance due"
    assert text_of("each, discount") == "each, discount"


def test_string_spanning_a_line_break():
    assert text_of("Lopez (maria@example.com)") == "Lopez\n(maria@example.com)"


def test_missing_and_empty_strings():
    assert find_span("Mario", SOURCE) is None
    assert find_span("   ", SOURCE) is None


def test_numbers_match_by_value():
    assert text_of(1250) == "1,250.00"
    assert text_of(1250.0) == "1,250.00"
    assert text_of(4984.5) == "4,984.50"
    assert text_of(-15.5) == "-15.5"
    assert text_of(15.5) == "15.5"
    assert find_span(99, SOURCE) is None


def test_digits_inside_dates_and_ids_are_not_numbers():
    assert text_of(4) == "4"
    assert find_span(4, SOURCE).start == SOURCE.index("4 widgets")
    assert find_span(42, SOURCE) is None
    assert find_span(2024, SOURCE) is None
    assert find_span(13, SOURCE) is None


def test_non_scalar_values_have_no_span():
    assert find_span(True, "True 1") is None
    assert find_span(None, "None") is None
    assert find_span(["a"], "a") is None


def test_find_spans_walks_nested_data():
    data = {
        "order": "ORD-0042",
        "customer": {"name": "Maria Lopez", "vip": True, "phone": None},
        "lines": [{"qty": 4, "price": 1250.0}],
        "currency": "USD",
    }
    spans = find_spans(data, SOURCE)
    assert set(spans) == {"order", "customer.name", "lines[0].qty", "lines[0].price", "currency"}
    assert spans["order"].text == "ORD-0042"
    assert spans["customer.name"].text == "Maria  Lopez"
    assert spans["lines[0].price"].text == "1,250.00"
    assert spans["currency"] is None


def test_repeated_number_is_resolved_by_the_nearest_string_sibling():
    source = "Pens     2   3.00\nPaper    5   9.50\nStaples  2   1.25\n"
    data = {"items": [{"name": "Pens", "qty": 2}, {"name": "Paper", "qty": 5}, {"name": "Staples", "qty": 2}]}
    spans = find_spans(data, source)
    assert spans["items[0].qty"].start == source.index("2   3.00")
    assert spans["items[2].qty"].start == source.index("2   1.25")
