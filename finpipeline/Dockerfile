# start from official Python image
FROM python:3.11-slim

# set working directory inside container
WORKDIR /app

# install Poetry inside container
RUN pip install poetry

# copy dependency files first (layer caching)
COPY pyproject.toml poetry.lock* ./

# install dependencies without creating a virtualenv
# inside a container the whole environment is isolated already
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --only main --no-root

# copy the rest of your code
COPY finpipeline/src/ ./src/
COPY finpipeline/migrations/ ./migrations/
COPY finpipeline/alembic.ini ./

# Railway supplies PORT at runtime; 8000 remains the local default.
EXPOSE 8000

# Shell expansion is intentional so Railway's assigned PORT is respected.
CMD ["sh", "-c", "uvicorn src.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
