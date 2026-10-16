"""add India market layer

Revision ID: c4f018c2ae12
Revises: 86c7434a3f20
Create Date: 2026-10-17
"""
from alembic import op
import sqlalchemy as sa

revision = "c4f018c2ae12"
down_revision = "86c7434a3f20"
branch_labels = None
depends_on = None


INSTRUMENTS = [
    ("^NSEI", "Nifty 50", "india", "index", "INR", "NSE", "Asia/Kolkata", "broad-market"),
    ("^BSESN", "BSE Sensex", "india", "index", "INR", "BSE", "Asia/Kolkata", "broad-market"),
    ("^NSEBANK", "Nifty Bank", "india", "index", "INR", "NSE", "Asia/Kolkata", "financials"),
    ("^INDIAVIX", "India VIX", "india", "index", "INR", "NSE", "Asia/Kolkata", "volatility"),
    ("RELIANCE.NS", "Reliance Industries", "india", "equity", "INR", "NSE", "Asia/Kolkata", "energy"),
    ("TCS.NS", "Tata Consultancy Services", "india", "equity", "INR", "NSE", "Asia/Kolkata", "technology"),
    ("HDFCBANK.NS", "HDFC Bank", "india", "equity", "INR", "NSE", "Asia/Kolkata", "financials"),
    ("INFY.NS", "Infosys", "india", "equity", "INR", "NSE", "Asia/Kolkata", "technology"),
    ("ICICIBANK.NS", "ICICI Bank", "india", "equity", "INR", "NSE", "Asia/Kolkata", "financials"),
    ("HINDUNILVR.NS", "Hindustan Unilever", "india", "equity", "INR", "NSE", "Asia/Kolkata", "consumer"),
    ("ITC.NS", "ITC", "india", "equity", "INR", "NSE", "Asia/Kolkata", "consumer"),
    ("SBIN.NS", "State Bank of India", "india", "equity", "INR", "NSE", "Asia/Kolkata", "financials"),
    ("BHARTIARTL.NS", "Bharti Airtel", "india", "equity", "INR", "NSE", "Asia/Kolkata", "telecom"),
    ("LT.NS", "Larsen & Toubro", "india", "equity", "INR", "NSE", "Asia/Kolkata", "industrial"),
    ("USDINR=X", "USD/INR", "india", "fx", "INR", "FX", "Asia/Kolkata", "currency"),
    ("BZ=F", "Brent crude", "india", "commodity", "USD", "NYMEX", "America/New_York", "energy"),
    ("AAPL", "Apple", "global", "equity", "USD", "NASDAQ", "America/New_York", "technology"),
    ("GOOGL", "Alphabet", "global", "equity", "USD", "NASDAQ", "America/New_York", "technology"),
    ("MSFT", "Microsoft", "global", "equity", "USD", "NASDAQ", "America/New_York", "technology"),
    ("TSLA", "Tesla", "global", "equity", "USD", "NASDAQ", "America/New_York", "consumer"),
]

MACRO_SERIES = [
    ("CPI", "CPIAUCSL", "global", "monthly", "fred", False),
    ("FEDFUNDS", "FEDFUNDS", "global", "monthly", "fred", False),
    ("UNRATE", "UNRATE", "global", "monthly", "fred", False),
    ("GDP", "GDP", "global", "quarterly", "fred", False),
    ("T10Y2Y", "T10Y2Y", "global", "daily", "fred", False),
    ("INDIA_CPI", "INDCPIALLMINMEI", "india", "monthly", "fred", False),
    ("INDIA_CALL_RATE", "IRSTCI01INM156N", "india", "monthly", "fred", False),
    ("INDIA_10Y_YIELD", "INDIRLTLT01STM", "india", "monthly", "fred", False),
    ("INDIA_REAL_GDP", "NGDPRNSAXDCINQ", "india", "quarterly", "fred", False),
    ("INDIA_EPU", "INDEPUINDXM", "india", "monthly", "fred", False),
    ("INDIA_MANUFACTURING_YOY", "INDPRMNTO01GYSAM", "india", "monthly", "fred", False),
    ("INDIA_USDINR", "DEXINUS", "india", "daily", "fred", False),
    ("INDIA_REPO_RATE", "RBI_REPO_CURATED", "india", "event", "rbi", True),
]


def upgrade():
    op.create_table(
        "instruments",
        sa.Column("ticker", sa.String(32), primary_key=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("asset_type", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("sector", sa.String(40)),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.CheckConstraint("market IN ('india', 'global')", name="ck_instrument_market"),
    )
    instruments = sa.table(
        "instruments",
        sa.column("ticker", sa.String()), sa.column("display_name", sa.String()),
        sa.column("market", sa.String()), sa.column("asset_type", sa.String()),
        sa.column("currency", sa.String()), sa.column("exchange", sa.String()),
        sa.column("timezone", sa.String()), sa.column("sector", sa.String()),
    )
    op.bulk_insert(instruments, [dict(zip(
        ("ticker", "display_name", "market", "asset_type", "currency", "exchange", "timezone", "sector"), row
    )) for row in INSTRUMENTS])

    op.alter_column("stock_prices", "ticker", type_=sa.String(32), existing_type=sa.String(10))
    for column in ("open", "high", "low", "close"):
        op.alter_column("stock_prices", column, type_=sa.Numeric(18, 6), existing_type=sa.Numeric(10, 2))
    op.add_column("stock_prices", sa.Column("adjusted_close", sa.Numeric(18, 6)))
    op.add_column("stock_prices", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))

    op.create_table(
        "macro_series",
        sa.Column("indicator", sa.String(50), primary_key=True),
        sa.Column("series_id", sa.String(64), nullable=False, unique=True),
        sa.Column("market", sa.String(16), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("manually_curated", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    series = sa.table(
        "macro_series",
        sa.column("indicator", sa.String()), sa.column("series_id", sa.String()),
        sa.column("market", sa.String()), sa.column("frequency", sa.String()),
        sa.column("source", sa.String()), sa.column("manually_curated", sa.Boolean()),
    )
    op.bulk_insert(series, [dict(zip(
        ("indicator", "series_id", "market", "frequency", "source", "manually_curated"), row
    )) for row in MACRO_SERIES])
    op.add_column("economic_indicators", sa.Column("series_id", sa.String(64)))
    op.add_column("economic_indicators", sa.Column("market", sa.String(16), server_default="global"))
    op.add_column("economic_indicators", sa.Column("source", sa.String(30), server_default="fred"))
    op.add_column("economic_indicators", sa.Column("manually_curated", sa.Boolean, server_default=sa.false()))
    op.add_column("economic_indicators", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    for indicator, series_id, *_ in MACRO_SERIES[:5]:
        op.execute(sa.text("UPDATE economic_indicators SET series_id=:series WHERE indicator=:indicator").bindparams(series=series_id, indicator=indicator))


def downgrade():
    for column in ("updated_at", "manually_curated", "source", "market", "series_id"):
        op.drop_column("economic_indicators", column)
    op.drop_table("macro_series")
    op.drop_column("stock_prices", "updated_at")
    op.drop_column("stock_prices", "adjusted_close")
    for column in ("open", "high", "low", "close"):
        op.alter_column("stock_prices", column, type_=sa.Numeric(10, 2), existing_type=sa.Numeric(18, 6))
    op.alter_column("stock_prices", "ticker", type_=sa.String(10), existing_type=sa.String(32))
    op.drop_table("instruments")
