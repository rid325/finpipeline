import psycopg2
import time
from src.config import (
    DATABASE_URL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD,
    DB_CONNECT_RETRIES, DB_CONNECT_TIMEOUT,
)


def _normalized_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _connect_once():
    common = {"connect_timeout": DB_CONNECT_TIMEOUT, "application_name": "finpipeline"}
    if DATABASE_URL:
        return psycopg2.connect(_normalized_database_url(DATABASE_URL), **common)
    if not DB_USER:
        raise RuntimeError("Set DATABASE_URL or DB_USER in the environment")
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER,
        password=DB_PASSWORD, **common
    )


def get_connection():
    """Return a verified connection, retrying briefly when an idle Neon compute wakes."""
    last_error = None
    for attempt in range(DB_CONNECT_RETRIES + 1):
        conn = None
        try:
            conn = _connect_once()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            conn.rollback()
            return conn
        except psycopg2.OperationalError as error:
            last_error = error
            if conn is not None:
                conn.close()
            if attempt < DB_CONNECT_RETRIES:
                time.sleep(attempt + 1)
    raise last_error


def test_connection():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT version();")
        version = cursor.fetchone()
        print(f"Connected to: {version[0]}")
        cursor.close()
        conn.close()
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False


if __name__ == "__main__":
    test_connection()
