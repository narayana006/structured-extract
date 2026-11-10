"""End-to-end example with a dataclass schema and a fake model.

Run with:  python examples/quickstart.py

Swap ``fake_llm.reply`` for a function that calls your model: anything that
takes a prompt string and returns the reply string.
"""

import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from structured_extract import extract

import fake_llm


@dataclass
class LineItem:
    description: str
    quantity: int
    amount: float


@dataclass
class Invoice:
    invoice_number: str
    vendor: str
    customer: str
    issue_date: datetime.date
    currency: str
    total: float
    line_items: list[LineItem]
    due_date: Optional[str] = None


text = (Path(__file__).parent / "invoice.txt").read_text()
result = extract(Invoice, text, complete=fake_llm.reply)

invoice = result.value
print(f"{invoice.invoice_number}: {invoice.customer} owes {invoice.total} {invoice.currency}")
print(f"issued {invoice.issue_date:%d %b %Y}, {len(invoice.line_items)} line items, first: {invoice.line_items[0]}")
print()
for number, attempt in enumerate(result.attempts, start=1):
    print(f"attempt {number}: {'accepted' if attempt.ok else 'rejected'}")
    for error in attempt.errors:
        print(f"  - {error}")
print("repairs on the accepted reply:", result.repairs)
print()
for path in ("invoice_number", "vendor", "total", "line_items[1].quantity"):
    span = result.spans[path]
    print(f"{path:22} -> chars {span.start}-{span.end}: {span.text!r}")
print("not found in the source:", result.ungrounded)
