from src.db import get_connection
from datetime import date


def seed_stock_prices():
    conn = get_connection()
    cursor = conn.cursor()

    # sample data — 3 days of AAPL prices
    sample_data = [
        ('AAPL', date(2024, 1, 2), 185.20, 186.50, 183.10, 185.92, 55000000),
        ('AAPL', date(2024, 1, 3), 184.50, 185.10, 182.30, 184.25, 48000000),
        ('AAPL', date(2024, 1, 4), 182.00, 183.40, 180.50, 181.91, 52000000),
    ]

    inserted = 0
    for row in sample_data:
        try:
            cursor.execute("""
                INSERT INTO stock_prices (ticker, date, open, high, low, close, volume)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT uq_ticker_date DO NOTHING
            """, row)
            inserted += cursor.rowcount  # 1 if inserted, 0 if skipped
        except Exception as e:
            print(f"Error inserting {row}: {e}")
            conn.rollback()

    conn.commit()
    print(f"Inserted {inserted} rows into stock_prices")
    cursor.close()
    conn.close()


def verify_data():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT ticker, date, close FROM stock_prices ORDER BY date")
    rows = cursor.fetchall()

    print("\nstock_prices table contents:")
    for row in rows:
        print(f"  {row[0]} | {row[1]} | ${row[2]}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    seed_stock_prices()
    verify_data()
