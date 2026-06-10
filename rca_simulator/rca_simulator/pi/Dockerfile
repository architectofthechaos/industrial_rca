# S2.2 — PI Web API simulator image. Build context = app root (rca_simulator/).
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY rca_simulator ./rca_simulator
COPY fixtures ./fixtures
RUN uv pip install --system .

EXPOSE 8000
ENV FIXTURE_PATH=/app/fixtures/refplant \
    SCENARIO=seal_leak_progression

CMD ["uvicorn", "rca_simulator.pi.app:build_default_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
