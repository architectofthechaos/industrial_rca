# S2.6 — SharePoint/Graph document simulator image. Build context = app root.
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY rca_simulator ./rca_simulator
COPY fixtures ./fixtures
RUN uv pip install --system .

EXPOSE 8000
ENV DOCS_PATH=/app/fixtures/refplant/documents

CMD ["uvicorn", "rca_simulator.documents.app:build_default_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8000"]
