from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
MIGRATION_DATABASE_URL = os.getenv("MIGRATION_DATABASE_URL")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "finpipeline")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
FRED_API_KEY = os.getenv("FRED_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
AUTH_USERNAME = os.getenv("AUTH_USERNAME")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD")
ENABLE_APSCHEDULER = os.getenv("ENABLE_APSCHEDULER", "false").lower() in {"1", "true", "yes"}
DB_CONNECT_RETRIES = int(os.getenv("DB_CONNECT_RETRIES", "2"))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))
NEWS_FEEDS_ENABLED = {
    item.strip() for item in os.getenv("NEWS_FEEDS_ENABLED", "").split(",") if item.strip()
}
