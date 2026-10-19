#!/usr/bin/env python3
"""Measure deterministic news tagging against the hand-labeled CSV."""
import csv
import json
from pathlib import Path

from src.news import evaluate_tagging_rows


def main() -> None:
    path = Path(__file__).resolve().parents[1] / "eval" / "news_tagging.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    print(json.dumps(evaluate_tagging_rows(rows), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
