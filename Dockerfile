# Klinikka-avustajan REST-rajapinta konttina.
#   docker compose up --build      -> http://localhost:8000/docs
# Azure-avaimet tulevat ajonaikaisesti .env-tiedostosta (docker-compose.yml), ei koskaan imageen.

FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PYDANTIC_AI_NO_BANNER=1 \
    MLFLOW_DISABLE_AGENT_HINT=1

WORKDIR /app

# Riippuvuudet omaksi kerrokseen: koodimuutos ei asenna kirjastoja uudelleen.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY data ./data
RUN uv sync --locked --no-dev

# Ei ajeta rootina. Hakuindeksin kansio luodaan valmiiksi, jotta volyymi saa oikeat oikeudet.
RUN useradd --create-home --uid 1000 app && mkdir -p /app/chroma_db && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["/app/.venv/bin/uvicorn", "klinikka.api:app", "--host", "0.0.0.0", "--port", "8000"]
