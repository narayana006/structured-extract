import json
import sys
from pathlib import Path

import pytest

from structured_extract.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SCHEMA = str(EXAMPLES / "invoice.schema.json")
INVOICE = str(EXAMPLES / "invoice.txt")
FAKE_LLM = f'"{sys.executable}" "{EXAMPLES / "fake_llm.py"}"'


def test_prompt(capsys):
    assert main(["prompt", INVOICE, "--schema", SCHEMA]) == 0
    out = capsys.readouterr().out
    assert "JSON Schema:" in out and "NORTHWIND PAPER SUPPLY CO." in out


def test_check_example_reply(capsys):
    code = main(["check", str(EXAMPLES / "model_reply.txt"), "--schema", SCHEMA, "--source", INVOICE])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["valid"] is True
    assert report["data"]["total"] == 764.88
    assert "removed a trailing comma" in report["repairs"]
    assert report["spans"]["total"]["text"] == "764.88"
    assert report["spans"]["line_items[1].quantity"]["text"] == "4"
    assert all(span is not None for span in report["spans"].values())


def test_check_invalid_reply_exits_1(tmp_path, capsys):
    reply = tmp_path / "reply.txt"
    reply.write_text('{"invoice_number": "17"}')
    assert main(["check", str(reply), "--schema", SCHEMA]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["valid"] is False
    assert "invoice_number: does not match pattern ^INV-\\d{4}-\\d{4}$" in report["errors"]
    assert "spans" not in report


def test_check_require_grounding(tmp_path, capsys):
    schema = tmp_path / "schema.json"
    schema.write_text('{"type": "object", "properties": {"city": {"type": "string"}}}')
    source = tmp_path / "source.txt"
    source.write_text("Shipped from Lyon.")
    reply = tmp_path / "reply.txt"
    reply.write_text('{"city": "Paris"}')
    args = ["check", str(reply), "--schema", str(schema)]
    assert main(args + ["--require-grounding"]) == 2
    capsys.readouterr()
    assert main(args + ["--source", str(source)]) == 0
    capsys.readouterr()
    assert main(args + ["--source", str(source), "--require-grounding"]) == 1
    assert "does not appear in the document" in capsys.readouterr().out


def test_run_with_command_retries_until_valid(capsys):
    code = main(["run", INVOICE, "--schema", SCHEMA, "--llm-cmd", FAKE_LLM, "--report"])
    report = json.loads(capsys.readouterr().out)
    assert code == 0
    assert report["data"]["invoice_number"] == "INV-2024-0317"
    assert len(report["attempts"]) == 2
    assert report["attempts"][0]["errors"] == [
        "total: required field is missing",
        "issue_date: is not a valid date: 'March 14, 2024'",
    ]


def test_run_plain_output_and_exhausted_retries(capsys):
    assert main(["run", INVOICE, "--schema", SCHEMA, "--llm-cmd", FAKE_LLM]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 764.88
    assert main(["run", INVOICE, "--schema", SCHEMA, "--llm-cmd", FAKE_LLM, "--max-retries", "0"]) == 1
    assert "no valid result after 1 attempt(s)" in capsys.readouterr().err


def test_run_reports_a_failing_command(capsys):
    failing = f'"{sys.executable}" -c "import sys; sys.exit(3)"'
    assert main(["run", INVOICE, "--schema", SCHEMA, "--llm-cmd", failing]) == 2
    assert "exited with status 3" in capsys.readouterr().err


def test_missing_schema_file(capsys):
    assert main(["prompt", INVOICE, "--schema", "/no/such/schema.json"]) == 2
    assert "structured-extract:" in capsys.readouterr().err
