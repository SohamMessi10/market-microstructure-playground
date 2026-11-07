# Market Microstructure Playground

A limit order book and matching engine with price-time priority, small enough to step through
by hand. Work in progress: the full README arrives with the last milestone.

![Stepping through a replay: a buy order sweeps the 101 queue and part of 102](docs/screenshots/replay-sweep.png)

```bash
python -m pip install -e ".[dev]"
mmp replay examples/walkthrough.jsonl
mmp view examples/walkthrough.jsonl
```

`mmp replay` prints a log of every event and trade. `mmp view` writes `walkthrough.html`: open
it in a browser and step through the replay.

- [`docs/design.md`](docs/design.md): the exchange rules, the script format, and the design.
- [`docs/walkthrough.md`](docs/walkthrough.md): a sequence of trades worked out by hand.
- [`docs/demo/`](docs/demo): the step-through pages for the two example scripts.
- [`examples/`](examples): scripts to replay. `tests/golden/` holds their expected output.
- [`PROGRESS.md`](PROGRESS.md): what's done and what's next.
