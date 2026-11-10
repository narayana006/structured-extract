# structured-extract

Schema in, validated JSON out: extract structured data from messy text with retries, repair and per-field confidence.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A Python library (TypeScript version planned).

**The problem it solves:** Turning invoices, resumes and emails into reliable JSON needs validation, repair and retries every time.

## Who it is for

Developers who need dependable structured data out of invoices, resumes, emails and other free text.

## How it will work

1. You describe the data you want as a schema.
2. The library asks a model to fill it in, validates the result and, if it is invalid, sends the errors back for a corrected attempt.
3. You get a validated object with a confidence score and the source text for each field.

## Planned features

Unticked items are not built yet.

- [ ] Pydantic (Python) and Zod (TypeScript) schemas
- [ ] Validate-and-repair loop with bounded retries
- [ ] Per-field confidence scores
- [ ] Source span citations for each extracted field
- [ ] Batch mode for large document sets

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```python
invoice = extract(Invoice, text)
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## License

[MIT](LICENSE)
