import importlib


def test_database_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example:5432/app")
    monkeypatch.setenv("SECRET_KEY", "test-only-secret")
    monkeypatch.delenv("AUTH_USERNAME", raising=False)
    monkeypatch.delenv("AUTH_PASSWORD", raising=False)

    import src.config as config
    import src.db as db

    importlib.reload(config)
    importlib.reload(db)
    monkeypatch.setattr(db.psycopg2, "connect", lambda *args, **kwargs: (args, kwargs))

    args, kwargs = db.get_connection()
    assert args == ("postgresql://user:pass@db.example:5432/app",)
    assert kwargs == {}


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
