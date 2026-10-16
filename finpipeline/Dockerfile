# start from official Python image
FROM python:3.11-slim

# set working directory inside container
WORKDIR /app

# install Poetry inside container
RUN pip install --no-cache-dir poetry==2.3.2

# copy dependency files first (layer caching)
COPY pyproject.toml poetry.lock* ./

# install dependencies without creating a virtualenv
# inside a container the whole environment is isolated already
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

# copy the rest of your code
COPY finpipeline/src/ ./src/
COPY finpipeline/dashboard/ ./dashboard/
COPY finpipeline/migrations/ ./migrations/
COPY finpipeline/data/ ./data/
COPY finpipeline/alembic.ini ./

RUN useradd --create-home --uid 10001 finpipeline \
    && chown -R finpipeline:finpipeline /app
USER finpipeline

# Railway supplies PORT at runtime; 8000 remains the local default.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

# Apply schema changes on every cold start, then launch the API. Shell expansion
# is intentional so Railway, Render, Koyeb, and similar hosts can supply PORT.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn src.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
