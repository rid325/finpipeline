# News tagging evaluation status

The requested 50-headline evaluation is intentionally not checked in. On 17 October 2026, the configured Economic Times, Mint, and Business Standard market feeds were technically live, but their published terms limit automated reuse and/or AI evaluation without written permission. Moneycontrol's current RSS endpoints returned HTTP 403; old mirror feeds contained only 2009 items.

Because the project rules say to respect publisher terms, copying those headlines into `eval/news_tagging.csv` would be the wrong result. The file therefore contains only its schema and no fabricated examples. Precision and recall are **not reported** because the labeled sample size is zero. Unit tests use clearly synthetic strings to test boundary, capitalization, ticker, and sector behavior.

Feeds remain config-driven but disabled by default. After written permission is obtained, enable exact feed IDs with `NEWS_FEEDS_ENABLED`, hand-label 50 permitted headlines, and calculate:

- precision = correct predicted tags / all predicted tags;
- recall = correct predicted tags / all expected tags;
- results split by ticker and sector, with every false positive and false negative retained.

Terms/source checks:

- Economic Times RSS: <https://economictimes.indiatimes.com/rss.cms>
- Mint terms and RSS: <https://www.livemint.com/terms-of-use>, <https://www.livemint.com/rss>
- Business Standard terms: <https://www.business-standard.com/terms-conditions>
- Moneycontrol RSS services: <https://www.moneycontrol.com/news/rss-services/news/>
