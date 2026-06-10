"""Live smoke test for the source simulators.

Unlike the pytest suite (which exercises logic in-process), this drives each
simulator over its REAL wire protocol against the running stack — PI/Maximo/SAP/
Documents over HTTP, OPC UA via an OPC UA client, MQTT by subscribing to the
broker and decoding Sparkplug B. Intended to run after `task up`.

Usage:
    python smoke/smoke.py                 # check everything
    python smoke/smoke.py --only pi,mqtt  # subset
Exits non-zero if any selected check fails.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

import httpx

from rca_simulator.mqtt.sparkplug import decode_payload
from rca_simulator.pi.webid import encode_webid

HOST = "127.0.0.1"
PORTS = {"pi": 8001, "maximo": 8002, "sap": 8003, "documents": 8004}
OPCUA_ENDPOINT = "opc.tcp://127.0.0.1:4840"
OPCUA_NS = "urn:rca:sim:refplant"
MQTT_HOST, MQTT_PORT = "127.0.0.1", 1883


def _wait_http(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


# ───────────────────────────── HTTP sims ─────────────────────────────

def check_pi() -> str:
    base = f"http://{HOST}:{PORTS['pi']}"
    if not _wait_http(f"{base}/openapi.json"):
        raise RuntimeError("PI did not become reachable")
    wid = encode_webid("P-101A.discharge_pressure")

    def avg(day: int) -> float:
        start = f"2026-03-{1 + day:02d}T00:00:00Z"
        end = f"2026-03-{1 + day:02d}T01:00:00Z"
        r = httpx.get(f"{base}/streams/{wid}/summary",
                      params={"startTime": start, "endTime": end,
                              "summaryType": "Average", "summaryDuration": "60m"},
                      timeout=10.0)
        r.raise_for_status()
        return r.json()["Items"][0]["Value"]["Value"]

    rec = httpx.get(f"{base}/streams/{wid}/recorded",
                    params={"startTime": "2026-03-06T00:00:00Z",
                            "endTime": "2026-03-06T00:01:00Z"}, timeout=10.0)
    rec.raise_for_status()
    items = rec.json()["Items"]
    assert items and isinstance(items[0]["Value"], (int, float)), "no recorded points"
    assert avg(27) < avg(1) - 100, "seal-leak decay not visible in PI"
    return f"recorded {len(items)} pts; seal-leak decay present"


def check_maximo() -> str:
    base = f"http://{HOST}:{PORTS['maximo']}"
    if not _wait_http(f"{base}/openapi.json"):
        raise RuntimeError("Maximo did not become reachable")
    r = httpx.get(f"{base}/maxrest/oslc/os/mxwo",
                  params={"oslc.where": 'location="CRDU-P101A"'}, timeout=10.0)
    r.raise_for_status()
    wonums = {m["wonum"] for m in r.json()["member"]}
    assert {"WO-50012345", "WO-50012402"} <= wonums, f"missing seal-leak WOs: {wonums}"
    return f"P-101A work orders present ({len(wonums)})"


def check_sap() -> str:
    base = f"http://{HOST}:{PORTS['sap']}/sap/opu/odata/sap/PM_NOTIFICATION_SRV"
    if not _wait_http(f"http://{HOST}:{PORTS['sap']}/openapi.json"):
        raise RuntimeError("SAP did not become reachable")
    meta = httpx.get(f"{base}/$metadata", timeout=10.0)
    meta.raise_for_status()
    assert "NotificationSet" in meta.text, "metadata missing NotificationSet"
    tok = httpx.get(f"{base}/NotificationSet", headers={"X-CSRF-Token": "Fetch"}, timeout=10.0)
    assert tok.headers.get("x-csrf-token"), "CSRF token not issued"
    results = httpx.get(f"{base}/NotificationSet",
                        params={"$filter": "EQUNR eq '10001234'"}, timeout=10.0).json()["d"]["results"]
    assert results, "no SAP notifications for P-101A equipment"
    return f"metadata + CSRF + {len(results)} P-101A notification(s)"


def check_documents() -> str:
    base = f"http://{HOST}:{PORTS['documents']}"
    if not _wait_http(f"{base}/openapi.json"):
        raise RuntimeError("Documents did not become reachable")
    hits = httpx.get(f"{base}/search",
                     params={"q": "mechanical seal flush leak", "top": 3}, timeout=10.0).json()["value"]
    assert hits and hits[0]["asset"] == "P-101A", f"unexpected top hit: {hits[:1]}"
    content = httpx.get(f"{base}/drives/refplant/items/DS-P101A/content", timeout=10.0)
    content.raise_for_status()
    assert content.text, "empty document content"
    return f"search top={hits[0]['id']}; content {len(content.text)} bytes"


# ───────────────────────────── OPC UA ─────────────────────────────

def check_opcua() -> str:
    return asyncio.run(_check_opcua_async())


async def _check_opcua_async() -> str:
    from asyncua import Client, ua

    deadline = time.time() + 30.0
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            async with Client(OPCUA_ENDPOINT) as client:
                idx = await client.get_namespace_index(OPCUA_NS)
                node = client.get_node(ua.NodeId("P-101A.discharge_pressure", idx))
                value = await node.read_value()
                assert isinstance(value, (int, float)), f"non-numeric value {value!r}"

                # subscribe and confirm live 1 Hz updates flow to a subscriber
                updates: list[float] = []

                class _Handler:
                    def datachange_notification(self, n, v, d):  # noqa: ANN001
                        updates.append(v)

                sub = await client.create_subscription(500, _Handler())
                await sub.subscribe_data_change(node)
                for _ in range(10):
                    if len(updates) >= 2:
                        break
                    await asyncio.sleep(0.5)
                await sub.delete()
                assert len(updates) >= 2, "no live subscription updates received"
                return f"read={value:.1f}; subscription got {len(updates)} updates"
        except Exception as exc:  # noqa: BLE001 (broad: server may still be booting)
            last_err = exc
            await asyncio.sleep(1.0)
    raise RuntimeError(f"OPC UA not reachable: {last_err}")


# ───────────────────────────── MinIO / S3 ─────────────────────────────

def check_minio() -> str:
    from minio import Minio

    from rca_simulator.documents.s3_variant import seed_bucket

    client = Minio(f"{HOST}:9000", access_key="minioadmin",
                   secret_key="minioadmin", secure=False)
    deadline = time.time() + 30.0
    ready = False
    while time.time() < deadline and not ready:
        try:
            client.list_buckets()
            ready = True
        except Exception:  # noqa: BLE001 (server may still be booting)
            time.sleep(1.0)
    if not ready:
        raise RuntimeError("MinIO not reachable")

    bucket = "refplant-docs-smoke"
    seed_bucket(client, bucket, "fixtures/refplant/documents")
    objs = list(client.list_objects(bucket, recursive=True))
    assert len(objs) >= 6, f"expected >=6 objects, got {len(objs)}"

    resp = client.get_object(bucket, "datasheet/DS-P101A.pdf")
    body = resp.read().decode("utf-8")
    resp.close()
    resp.release_conn()
    assert "mechanical seal" in body.lower(), "datasheet content missing expected text"
    return f"seeded {len(objs)} objects; GetObject ok"


# ───────────────────────────── MQTT ─────────────────────────────

def check_mqtt() -> str:
    import paho.mqtt.client as mqtt

    received: list[tuple[str, bytes]] = []
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rca-smoke")
    client.on_message = lambda c, u, m: received.append((m.topic, m.payload))

    deadline = time.time() + 30.0
    connected = False
    while time.time() < deadline and not connected:
        try:
            client.connect(MQTT_HOST, MQTT_PORT)
            connected = True
        except OSError:
            time.sleep(1.0)
    if not connected:
        raise RuntimeError("MQTT broker not reachable")

    client.subscribe("spBv1.0/#")
    client.loop_start()
    # collect retained BIRTH + a few live DDATA frames
    end = time.time() + 8.0
    while time.time() < end and not (
        any("/DBIRTH/" in t for t, _ in received) and
        sum("/DDATA/" in t for t, _ in received) >= 2
    ):
        time.sleep(0.3)
    client.loop_stop()
    client.disconnect()

    dbirths = [(t, p) for t, p in received if "/DBIRTH/" in t]
    ddatas = [(t, p) for t, p in received if "/DDATA/" in t]
    assert dbirths, "no retained DBIRTH received (alias declaration missing)"
    assert ddatas, "no DDATA frames received"

    # resolve a DDATA value via the BIRTH alias map for the same device
    btopic, bpayload = dbirths[0]
    device = btopic.split("/")[-1]
    alias_to_name = {m.alias: m.name for m in decode_payload(bpayload).metrics}
    dpayload = next(p for t, p in ddatas if t.endswith(f"/{device}"))
    metrics = decode_payload(dpayload).metrics
    resolved = {alias_to_name.get(m.alias): m.value for m in metrics}
    assert any(isinstance(v, (int, float)) for v in resolved.values()), "no numeric DDATA value"
    return f"{len(dbirths)} BIRTH + {len(ddatas)} DATA; resolved {device} metrics"


# ───────────────────────────── runner ─────────────────────────────

CHECKS = {
    "pi": check_pi,
    "maximo": check_maximo,
    "sap": check_sap,
    "documents": check_documents,
    "opcua": check_opcua,
    "mqtt": check_mqtt,
    "minio": check_minio,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Live smoke test for the simulators.")
    parser.add_argument("--only", help="comma-separated subset, e.g. pi,mqtt")
    args = parser.parse_args()

    names = args.only.split(",") if args.only else list(CHECKS)
    failures = 0
    print("── simulator smoke test ──")
    for name in names:
        check = CHECKS.get(name.strip())
        if check is None:
            print(f"  ?  {name:<10} unknown check")
            failures += 1
            continue
        try:
            detail = check()
            print(f"  ✓  {name:<10} {detail}")
        except Exception as exc:  # noqa: BLE001 (report any failure as a red check)
            print(f"  ✗  {name:<10} {type(exc).__name__}: {exc}")
            failures += 1

    total = len(names)
    print(f"── {total - failures}/{total} passed ──")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
