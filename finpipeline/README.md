# finpipeline

A financial data pipeline project built with Python, PostgreSQL, and Poetry.

---

## Questions

### What is Poetry and why is it better than just using pip?

Poetry is a dependency and packaging manager for Python. Unlike pip, it manages both
dependencies and virtual environments in one tool, and it uses a lock file
(`poetry.lock`) to pin exact versions of every package — including transitive
dependencies. This means anyone who clones the project gets the exact same environment.
With plain pip you'd need to manually maintain `requirements.txt` and a separate tool
like `venv`, and version conflicts are easy to miss.

### Why does config live in .env and not in config.py directly?

If credentials were hardcoded in `config.py`, they'd end up in version control and
anyone with access to the repo (or a public GitHub) could read them. `.env` is kept
out of git via `.gitignore`, so secrets never leave your machine. In production you'd
set the same variables as server environment variables — the code itself never changes
between local and production, only the environment does.

### What is a database connection and what does psycopg2.connect() actually do under the hood?

A database connection is a persistent TCP socket between your Python process and the
Postgres server. When you call `psycopg2.connect()`, the library performs a TCP
handshake with the server, authenticates using the credentials you provide, and
negotiates a session. After that, every `cursor.execute()` sends a query over that
open socket and reads back results. Connections are expensive to open, which is why
real applications use connection pools rather than opening a new one per query.

### What would happen if you committed .env to a public GitHub repo?

Anyone on the internet could read your database credentials. Automated bots scan
GitHub continuously for exposed secrets and can exfiltrate or destroy your data within
minutes of a push. Even if you delete the file in a later commit, the credentials are
still visible in the git history. You'd need to rotate every secret immediately and
audit for any unauthorized access.

---

## Live API

Deployed on Railway: https://finpipeline-production.up.railway.app

```
GET /health
GET /metrics
GET /stocks/summary
GET /stocks/{ticker}/history
GET /stocks/{ticker}/volatility
GET /stocks/{ticker}/rolling-average
GET /macro/{indicator}
GET /pipeline/runs
GET /docs
```

## Setup

```bash
# Install dependencies
poetry install

# Copy and fill in your credentials
cp .env.example .env

# Test the database connection
poetry run python src/db.py
```
