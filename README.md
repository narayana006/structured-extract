# structured-extract

> Schema in, validated JSON out: extract structured data from messy text with retries, repair and per-field confidence.

**Status:** 🚧 Early stage — design and roadmap published, implementation in progress. Stars, issues and ideas welcome.

## Why

Turning invoices, resumes and emails into reliable JSON needs validation, repair and retries every time.

## Planned features

- [ ] Pydantic (Python) and Zod (TypeScript) schemas
- [ ] Validate-and-repair loop with bounded retries
- [ ] Per-field confidence scores
- [ ] Source span citations for each extracted field
- [ ] Batch mode for large document sets

## Intended usage

```
invoice = extract(Invoice, text)
```

_The interface above is the target design and may change._

## Roadmap

1. Core implementation of the first feature set
2. Examples and tests
3. CI and first tagged release
4. Docs and integrations

## Contributing

Contributions are welcome. Open an issue to discuss an idea or pick an unchecked item from the feature list.

## License

[MIT](LICENSE)
