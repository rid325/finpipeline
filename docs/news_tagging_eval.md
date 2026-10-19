# News tagging evaluation

On 19 October 2026, 50 current RSS headlines were sampled in feed order and hand-labeled against the project's deliberately narrow ticker/index and sector taxonomy. The sample contains 17 Economic Times Markets, 17 Mint Markets, and 16 Business Standard Markets headlines. The labeled rows are in `eval/news_tagging.csv`; they are real headlines, not synthetic fixtures.

Run the reproducible measurement with:

```bash
PYTHONPATH=finpipeline poetry run python scripts/evaluate_news_tags.py
```

The current result is **100.0% precision and 65.7% recall**: 23 correct predicted tags, zero false positives, and 12 missed expected tags. These are micro-averaged tag decisions across both ticker and sector labels. The result is a small development-set measurement, not evidence of general model quality.

The misses show the intended tradeoff. The word-boundary dictionary avoids guessing, but misses implied sectors such as AI/chips → technology, renewable → energy, broking/brokerages → financials, Jio → telecom, and sugar producers → consumer. The ticker/index aliases performed better on this sample: explicit Sensex, Nifty, State Bank of India, Reliance/Jio, RIL, and Airtel mentions were tagged. No misses were hidden or relabeled after running the code.

Feed verification on the same date:

- Economic Times Markets: HTTP 200, 50 current RSS items.
- Mint Markets: HTTP 200, 35 current RSS items.
- Business Standard Markets: HTTP 200, 35 current RSS items.
- Moneycontrol: its advertised XML feeds returned data last published on 23 April 2024, so the source was dropped rather than presented as current.
- GDELT fallback: not used because three requested feeds were technically live; a direct verification request also returned HTTP 429 from the development environment.

Only feed-provided headline metadata, direct links, timestamps, and short snippets are ingested—never article bodies. Publisher RSS terms limit reuse, particularly for commercial syndication. Keep this as a non-commercial portfolio demonstration, retain direct attribution/links, and obtain written permission or disable a feed before broader or commercial reuse. Set `NEWS_FEEDS_ENABLED=false` to disable all feeds.
