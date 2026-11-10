"""Command-line interface: structured-extract prompt | check | run."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from typing import Any, Sequence

from . import __version__
from .extract import ExtractionError, build_prompt, check_output, extract
from .spans import Span


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _load_schema(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        schema = json.load(handle)
    if not isinstance(schema, dict):
        raise ValueError(f"{path} does not contain a JSON Schema object")
    return schema


def _spans_json(spans: dict[str, Span | None]) -> dict[str, Any]:
    return {
        path: None if span is None else {"start": span.start, "end": span.end, "text": span.text}
        for path, span in spans.items()
    }


def _emit(report: dict) -> None:
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _cmd_prompt(args: argparse.Namespace) -> int:
    sys.stdout.write(build_prompt(_load_schema(args.schema), _read(args.document)) + "\n")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    schema = _load_schema(args.schema)
    source = _read(args.source) if args.source else None
    data, _value, errors, repairs, spans = check_output(
        schema, _read(args.output), source, require_grounding=args.require_grounding
    )
    report: dict[str, Any] = {"valid": not errors, "errors": errors, "repairs": repairs, "data": data}
    if source is not None:
        report["spans"] = _spans_json(spans)
    _emit(report)
    return 0 if not errors else 1


def _command_callable(command: str, timeout: float):
    argv = shlex.split(command)
    if not argv:
        raise ValueError("--llm-cmd is empty")

    def complete(prompt: str) -> str:
        result = subprocess.run(
            argv, input=prompt, capture_output=True, text=True, timeout=timeout, check=False
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{argv[0]} exited with status {result.returncode}: {result.stderr.strip()}"
            )
        return result.stdout

    return complete


def _cmd_run(args: argparse.Namespace) -> int:
    schema = _load_schema(args.schema)
    text = _read(args.document)
    complete = _command_callable(args.llm_cmd, args.timeout)
    try:
        result = extract(
            schema,
            text,
            complete,
            max_retries=args.max_retries,
            require_grounding=args.require_grounding,
        )
    except ExtractionError as exc:
        print(f"structured-extract: {exc}", file=sys.stderr)
        if args.report:
            _emit({"valid": False, "attempts": [
                {"errors": a.errors, "response": a.response} for a in exc.attempts
            ]})
        return 1
    if args.report:
        _emit({
            "valid": True,
            "data": result.data,
            "repairs": result.repairs,
            "spans": _spans_json(result.spans),
            "attempts": [{"errors": a.errors, "repairs": a.repairs} for a in result.attempts],
        })
    else:
        _emit(result.data)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="structured-extract",
        description="Validate, repair and ground schema-driven extractions.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prompt = sub.add_parser("prompt", help="print the extraction prompt for a document")
    p_prompt.add_argument("document", help="text file to extract from, or - for stdin")
    p_prompt.add_argument("--schema", required=True, help="JSON Schema file")
    p_prompt.set_defaults(func=_cmd_prompt)

    p_check = sub.add_parser("check", help="repair and validate a model reply you already have")
    p_check.add_argument("output", help="file holding the model's reply, or - for stdin")
    p_check.add_argument("--schema", required=True, help="JSON Schema file")
    p_check.add_argument("--source", help="original document, to locate each field in it")
    p_check.add_argument(
        "--require-grounding", action="store_true",
        help="fail if a string or number is not found in --source",
    )
    p_check.set_defaults(func=_cmd_check)

    p_run = sub.add_parser("run", help="extract by piping prompts to a command of your choice")
    p_run.add_argument("document", help="text file to extract from, or - for stdin")
    p_run.add_argument("--schema", required=True, help="JSON Schema file")
    p_run.add_argument(
        "--llm-cmd", required=True, metavar="COMMAND",
        help="command that reads a prompt on stdin and writes the reply to stdout",
    )
    p_run.add_argument("--max-retries", type=int, default=2, help="repair attempts (default: 2)")
    p_run.add_argument("--timeout", type=float, default=120.0, help="seconds per call (default: 120)")
    p_run.add_argument("--require-grounding", action="store_true",
                       help="reject values that do not appear in the document")
    p_run.add_argument("--report", action="store_true",
                       help="print data plus repairs, spans and attempts")
    p_run.set_defaults(func=_cmd_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "require_grounding", False) and args.command == "check" and not args.source:
        print("structured-extract: --require-grounding needs --source", file=sys.stderr)
        return 2
    try:
        return args.func(args)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"structured-extract: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
