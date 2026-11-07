# Market Microstructure Playground

A limit order book and matching engine with price-time priority, small enough to step through
by hand. Work in progress: the full README arrives with the last milestone.

```bash
python -m pip install -e ".[dev]"
mmp replay examples/walkthrough.jsonl
```

- [`docs/design.md`](docs/design.md): the exchange rules, the script format, and the design.
- [`docs/walkthrough.md`](docs/walkthrough.md): a sequence of trades worked out by hand.
- [`examples/`](examples): scripts to replay. `tests/golden/` holds their expected output.
- [`PROGRESS.md`](PROGRESS.md): what's done and what's next.
