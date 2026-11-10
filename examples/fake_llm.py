"""A stand-in for a model, so the examples run offline.

Reads a prompt on stdin and writes a reply to stdout, like any command you
would pass to ``structured-extract run --llm-cmd``. Its first answer has two
mistakes (a date in the wrong format and a missing required field). When the
prompt contains the rejection reasons, it answers correctly.
"""

import sys

FIRST = """Here you go:
{
  "invoice_number": "INV-2024-0317",
  "vendor": "Northwind Paper Supply Co.",
  "customer": "Brightside Dental Group",
  "issue_date": "March 14, 2024",
  "currency": "USD",
  "line_items": [
    {"description": "A4 copy paper, 80gsm (box)", "quantity": 12, "amount": 462.00},
    {"description": "Thermal receipt rolls (case)", "quantity": 4, "amount": 245.00},
    {"description": "Delivery", "quantity": 1, "amount": 18.00},
  ]
}"""

SECOND = FIRST.replace("Here you go:\n", "").replace(
    '"issue_date": "March 14, 2024",',
    '"issue_date": "2024-03-14",\n  "due_date": "2024-04-13",\n  "total": 764.88,',
)


def reply(prompt: str) -> str:
    return SECOND if "It was rejected for these reasons" in prompt else FIRST


if __name__ == "__main__":
    sys.stdout.write(reply(sys.stdin.read()))
