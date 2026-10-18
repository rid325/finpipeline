import importlib
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class FakeCursor:
    def __init__(self):
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query):
        self.queries.append(query)


class FakeConnection:
    def __init__(self):
        self.test_cursor = FakeCursor()
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return self.test_cursor

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_database_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example:5432/app")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)

    import src.config as config
    import src.db as db

    importlib.reload(config)
    importlib.reload(db)
    calls = []
    connection = FakeConnection()

    def fake_connect(*args, **kwargs):
        calls.append((args, kwargs))
        return connection

    monkeypatch.setattr(db.psycopg2, "connect", fake_connect)

    returned = db.get_connection()
    args, kwargs = calls[0]
    assert returned is connection
    assert args == ("postgresql://user:pass@db.example:5432/app",)
    assert kwargs == {"application_name": "finpipeline", "connect_timeout": 10}
    assert connection.test_cursor.queries == ["SELECT 1"]
    assert connection.rolled_back is True


def test_connection_retries_a_sleeping_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@db.example:5432/app")
    monkeypatch.setenv("DB_CONNECT_RETRIES", "2")

    import src.config as config
    import src.db as db

    importlib.reload(config)
    importlib.reload(db)
    connection = FakeConnection()
    attempts = []

    def fake_connect(*args, **kwargs):
        attempts.append((args, kwargs))
        if len(attempts) == 1:
            raise db.psycopg2.OperationalError("compute is waking")
        return connection

    sleeps = []
    monkeypatch.setattr(db.psycopg2, "connect", fake_connect)
    monkeypatch.setattr(db.time, "sleep", sleeps.append)

    assert db.get_connection() is connection
    assert attempts[0][0][0].startswith("postgresql://")
    assert len(attempts) == 2
    assert sleeps == [1]


def test_stale_pipeline_runs_are_closed_before_a_new_run():
    import src.db as db

    class Cursor:
        rowcount = 2

        def execute(self, query, params):
            self.query = query
            self.params = params

    cursor = Cursor()
    as_of = datetime(2026, 10, 18, tzinfo=timezone.utc)

    assert db.close_stale_pipeline_runs(cursor, "yahoo_finance", as_of) == 4
    assert "INTERVAL '30 minutes'" in cursor.query
    assert cursor.params == (as_of, as_of, "yahoo_finance", as_of)


def test_job_cli_returns_nonzero_when_a_job_reports_errors(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    import src.jobs as jobs

    monkeypatch.setitem(
        jobs.JOBS,
        "news",
        lambda: {"total_inserted": 0, "errors": ["upstream unavailable"]},
    )

    assert jobs.main(["run", "news"]) == 1
    assert "upstream unavailable" in capsys.readouterr().err


def test_auth_has_no_default_published_user(monkeypatch):
    monkeypatch.setenv("DB_USER", "test")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)

    import src.config as config
    import src.auth as auth

    importlib.reload(config)
    importlib.reload(auth)
    assert auth.USERS == {}


def test_auth_user_comes_from_environment(monkeypatch):
    monkeypatch.setenv("DB_USER", "test")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    monkeypatch.setenv("AUTH_USERNAME", "portfolio-reviewer")
    monkeypatch.setenv("AUTH_PASSWORD", "not-checked-in")

    import src.config as config
    import src.auth as auth

    importlib.reload(config)
    importlib.reload(auth)
    assert set(auth.USERS) == {"portfolio-reviewer"}
    assert auth.verify_password(
        "not-checked-in", auth.USERS["portfolio-reviewer"]["hashed_password"]
    )


def test_market_workflow_separates_exchange_close_schedules_and_supports_backfill():
    workflow = (REPOSITORY_ROOT / ".github/workflows/market-ingestion.yml").read_text()

    assert "github.event.schedule == '37 10 * * 1-5'" in workflow
    assert "github.event.schedule == '37 22 * * 1-5'" in workflow
    assert "inputs.market == 'india'" in workflow
    assert "inputs.market == 'global'" in workflow
    assert workflow.count("inputs.backfill && '--backfill'") == 2


def test_macro_workflow_supports_manual_backfill():
    workflow = (REPOSITORY_ROOT / ".github/workflows/macro-ingestion.yml").read_text()

    assert "description: Fetch ten years" in workflow
    assert "inputs.backfill && '--backfill'" in workflow
