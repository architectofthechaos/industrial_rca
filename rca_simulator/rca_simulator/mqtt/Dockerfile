# S2.7 — MQTT Sparkplug B publisher image. Build context = app root (rca_simulator/).
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml README.md ./
COPY rca_simulator ./rca_simulator
COPY fixtures ./fixtures
RUN uv pip install --system .

ENV FIXTURE_PATH=/app/fixtures/refplant \
    SCENARIO=seal_leak_progression \
    MQTT_BROKER=mosquitto:1883

CMD ["python", "-m", "rca_simulator.mqtt.publisher"]
