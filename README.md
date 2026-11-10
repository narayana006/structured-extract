# structured-extract

Schema in, validated JSON out: extract structured data from messy text with a validate-and-repair loop, bounded retries and a source span for every field.

**Status: v0.1.0, working.** JSON repair, schema validation, the retry loop, source spans and a small CLI are implemented and tested. Per-field confidence scores and the TypeScript version are not built yet.

You bring the model as a plain function, `complete(prompt: str) -> str`. This library has no dependencies and never imports a vendor SDK, so it works with any provider, a local model, or a fake in your tests.

```python
from structured_extract import extract

result = extract(Invoice, text, complete=my_llm)

result.value      # an Invoice (dataclass or Pydantic model), validated
result.spans      # where each field was found in the text
result.attempts   # every prompt, reply and rejection reason
```

## How it works

1. Your schema (a JSON Schema dict, a dataclass or a Pydantic v2 model) is turned into a prompt together with the document.
2. The reply is parsed. Code fences, chatty prose around the JSON, single quotes, trailing commas, unquoted keys, Python literals and cut-off output are repaired locally, without another model call.
3. Near-miss types are coerced when it is lossless (`"764.88"` to `764.88` for a number field).
4. The result is validated against the schema. If it fails, the exact errors are sent back and the model gets another try, up to `max_retries` times.
5. Each string and number in the result is looked up in the source text, so you can show where it came from, or spot values that appear nowhere in the document.

## Install

Python 3.10 or newer.

```bash
pip install git+https://github.com/narayana006/structured-extract
```

Pydantic is optional. If you pass Pydantic models, install it yourself (`pip install "pydantic>=2"`).

## Quick start

Clone the repository to get the examples; they run offline against a scripted stand-in for a model (`examples/fake_llm.py`) whose first answer is deliberately wrong.

```bash
git clone https://github.com/narayana006/structured-extract
cd structured-extract
pip install -e .
python examples/quickstart.py
```

Output:

```text
INV-2024-0317: Brightside Dental Group owes 764.88 USD
issued 14 Mar 2024, 3 line items, first: LineItem(description='A4 copy paper, 80gsm (box)', quantity=12, amount=462.0)

attempt 1: rejected
  - total: required field is missing
  - issue_date: is not a valid date: 'March 14, 2024'
attempt 2: accepted
repairs on the accepted reply: ['removed a trailing comma']

invoice_number         -> chars 120-133: 'INV-2024-0317'
vendor                 -> chars 0-26: 'NORTHWIND PAPER SUPPLY CO.'
total                  -> chars 845-851: '764.88'
line_items[1].quantity -> chars 520-521: '4'
not found in the source: []
```

The first reply was missing `total` and had a date in the wrong format, so both errors were sent back. The second reply still had a trailing comma, which was fixed locally instead of costing a third call. Note that `vendor` was matched case-insensitively against the letterhead.

The core of `examples/quickstart.py`:

```python
import datetime
from dataclasses import dataclass
from typing import Optional

from structured_extract import extract


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


result = extract(Invoice, text, complete=fake_llm.reply)
invoice = result.value
```

To use a real model, replace `fake_llm.reply` with your own function. It receives the prompt as a string and must return the reply as a string; how it calls the model is up to you.

## Library reference

### `extract(schema, text, complete, *, max_retries=2, instructions="", coerce_types=True, require_grounding=False)`

Returns an `Extraction`:

| Attribute | Contents |
| --- | --- |
| `data` | The validated result as plain JSON data (dicts, lists, strings, numbers). |
| `value` | The same result as an instance of your dataclass or Pydantic model. For a JSON Schema dict it is `data`. |
| `spans` | `{path: Span or None}` for every string and number, e.g. `spans["line_items[0].amount"]`. A `Span` has `start`, `end` and `text`. |
| `ungrounded` | Paths whose value was not found in the source. |
| `attempts` | A list of `Attempt(prompt, response, errors, repairs)`, one per model call. |
| `repairs` | Fixes applied to the accepted reply. |

`complete` is called at most `max_retries + 1` times. If no reply validates, `ExtractionError` is raised; its `.attempts` holds the full history.

- `instructions` adds your own guidance to the prompt (for example "amounts are in GBP").
- `coerce_types=False` turns off type coercion, so `"36"` for an integer field is an error.
- `require_grounding=True` treats any string or number that cannot be found in the text as an error and sends it back to the model. Use it when every field should be copied verbatim; leave it off when fields are normalised or inferred (ISO dates from "March 14", categories, booleans).

### Schemas

- **JSON Schema dict.** Supported keywords: `type`, `properties`, `required`, `additionalProperties`, `items`, `minItems`, `maxItems`, `enum`, `const`, `minimum`, `maximum`, `exclusiveMinimum`, `exclusiveMaximum`, `minLength`, `maxLength`, `pattern`, `format` (`date`, `date-time`, `email`), `anyOf`, `oneOf`, `allOf` and local `$ref`. Other keywords are ignored.
- **Dataclass.** Fields may be `str`, `int`, `float`, `bool`, `datetime.date`, `Optional[...]`, `Literal[...]`, `list[...]`, `dict` or another dataclass. Fields without a default are required. `field(metadata={"description": "..."})` is passed to the model.
- **Pydantic v2 model.** The schema comes from `model_json_schema()` and the final object from `model_validate()`, so your own validators run too, and their error messages are fed back to the model like any other validation error.

### `extract_many(schema, texts, complete, **options)`

Runs `extract` over several documents in order and returns a list with an `Extraction` or an `ExtractionError` in each slot, so one bad document does not stop the batch. It is sequential; there is no concurrency or rate limiting yet.

### The building blocks

Each step is usable on its own:

```python
from structured_extract import parse_json, coerce, validate, find_span

parse_json("Sure! ```json\n{'name': 'Ada', age: 36,}\n```")
# ({'name': 'Ada', 'age': 36},
#  ['removed a Markdown code fence', 'converted non-standard quotes to double quotes',
#   'quoted an unquoted key', 'removed a trailing comma'])

schema = {"type": "object", "required": ["age"],
          "properties": {"age": {"type": "integer", "minimum": 0}}}

coerce({"age": "36"}, schema)
# ({'age': 36}, ["age: converted string '36' to number"])

[str(issue) for issue in validate({"age": -1}, schema)]
# ['age: must be >= 0, got -1']

find_span(1250.0, "Total due: 1,250.00 EUR")
# Span(start=11, end=19, text='1,250.00')
```

`check_output(schema, reply, source)` runs parse, coerce, validate and span lookup on a reply you already have, without calling a model. `build_prompt(schema, text)` returns the prompt.

## Command line

The package installs a `structured-extract` command with three subcommands. Schemas on the command line are JSON Schema files.

**Check a reply you already have.** `examples/model_reply.txt` is a typical chatty reply: prose, a code fence, single quotes on one line, a trailing comma and the total as a string.

```console
$ structured-extract check examples/model_reply.txt --schema examples/invoice.schema.json | head -9
{
  "valid": true,
  "errors": [],
  "repairs": [
    "removed a Markdown code fence",
    "converted non-standard quotes to double quotes",
    "removed a trailing comma",
    "total: converted string '764.88' to number"
  ],
```

The full report also contains the cleaned `data`. Add `--source examples/invoice.txt` to get a `spans` section, and `--require-grounding` to fail when a value is not in the source. The exit status is 0 when valid and 1 when not, so it can gate a pipeline.

**Run the whole loop with any command as the model.** The command receives the prompt on stdin and must print the reply on stdout:

```console
$ structured-extract run examples/invoice.txt --schema examples/invoice.schema.json --llm-cmd "python3 examples/fake_llm.py" | head -8
{
  "invoice_number": "INV-2024-0317",
  "vendor": "Northwind Paper Supply Co.",
  "customer": "Brightside Dental Group",
  "issue_date": "2024-03-14",
  "due_date": "2024-04-13",
  "total": 764.88,
  "currency": "USD",
```

Options: `--max-retries N` (default 2), `--timeout SECONDS` per call (default 120), `--require-grounding`, and `--report` to print repairs, spans and per-attempt errors along with the data.

**Print the prompt** to paste into a chat window or inspect:

```bash
structured-extract prompt examples/invoice.txt --schema examples/invoice.schema.json
```

## Features

- [x] JSON Schema, dataclass and Pydantic v2 schemas (Python)
- [x] JSON parsing with local repair of malformed model output
- [x] Validate-and-repair loop with bounded retries
- [x] Source span for each extracted string and number
- [x] Sequential batch helper (`extract_many`)
- [x] CLI: `check`, `run`, `prompt`
- [ ] Per-field confidence scores
- [ ] Concurrent batch mode with rate limiting
- [ ] Zod schemas and a TypeScript version
- [ ] Chunking for documents longer than the model's context window

## Limitations

- **No confidence scores.** The only signal today is whether a value was found in the source (`spans`, `ungrounded`).
- **Span lookup is literal.** Strings match exactly or ignoring case and whitespace; numbers match numerals of equal value. A value the model normalised (`"2024-03-14"` from "March 14, 2024") or inferred has no span. When a string occurs several times, the first occurrence is reported; for a repeated number, the occurrence closest to a string field of the same object is chosen, which is a heuristic and can pick the wrong one.
- **A span shows that the value appears in the text, not that it is the right value.** The model can still copy the wrong number.
- **The JSON Schema support is a subset** (listed above). There is no `patternProperties`, `if`/`then`, `dependentRequired`, `uniqueItems`, `multipleOf` or remote `$ref`.
- **JSON repair is best effort.** Badly broken output can be repaired into something that parses but is not what the model meant; the schema check is the safety net, so write a strict schema (`required`, `additionalProperties: false`).
- The whole document is sent in one prompt. Splitting long documents is up to you.
- Prompts are in English and not tuned for any particular model.

## Contributing

Bug reports are most useful with the model reply that was mis-parsed or the schema and value that were validated wrongly. Pull requests are welcome:

```bash
pip install -e ".[dev]"
pytest
```

Tests use scripted fake models only; nothing in the test suite calls a real model or the network.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
