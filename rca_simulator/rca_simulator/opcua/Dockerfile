# S2.5 — OPC UA server image. Build context = app root (rca_simulator/).
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY rca_simulator ./rca_simulator
COPY fixtures ./fixtures
RUN uv pip install --system .

EXPOSE 4840
ENV FIXTURE_PATH=/app/fixtures/refplant \
    SCENARIO=seal_leak_progression \
    OPCUA_ENDPOINT=opc.tcp://0.0.0.0:4840

CMD ["python", "-m", "rca_simulator.opcua.server"]
