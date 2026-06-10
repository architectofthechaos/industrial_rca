# ADR-0006: Time handling — UTC ISO 8601 everywhere, explicit time basis

- **Status**: Accepted
- **Date**: 2026-06-03
- **Deciders**: gvishnu

## Context

Time is the single most error-prone aspect of industrial data integration. Three distinct problems:

**1. Clock skew between systems.** PI server, DCS, Maximo, SAP, OPC servers all run their own clocks. Real-world drift of seconds to minutes is common. For sequence-of-events analysis in RCA, ordering matters at millisecond resolution.

**2. Timezone and DST chaos.** PI typically stores UTC but presents in local time. Maximo often stores local-time-without-TZ. SAP varies by deployment. Engineer reports say "around 3 PM." When a probe joins evidence from multiple sources, naive timestamps silently mis-align.

**3. Historian interpolation and compression.** PI compresses tags — a 1 Hz signal may have stored values every 60 seconds because nothing changed beyond the compression deviation. If you query "value at 14:32:17," PI interpolates and returns a number that was never measured. For RCA on transients, this is dangerous.

## Decision

1. **All timestamps in our system are UTC ISO 8601 with explicit timezone.** Internal Python type is `datetime` with `tzinfo` required. Pydantic models reject naive datetimes.

2. **Every connector normalizes to UTC at ingest.** Local-time-without-TZ sources require a `source_timezone` configuration per tenant per source. Connector ingestion fails loudly if `source_timezone` is unset on a source that needs it.

3. **Every evidence bundle carries a `time_basis` block:**
   ```python
   class TimeBasis(BaseModel):
       source_clock: str                # e.g., "pi_server_main"
       observed_offset_seconds: float   # observed offset from NTP at ingest
       offset_measurement_time: datetime
       source_timezone: str             # IANA timezone, e.g., "America/Chicago"
       confidence: Literal["ntp_synced", "configured", "estimated", "unknown"]
   ```
   This block accompanies every measurement series so the agent (and reviewers) can see how much temporal slop to allow.

4. **For sequence-of-events analysis, prefer SOE recorders over historian.** SOE recorders (DCS-native) use a single clock with millisecond timestamps. Historian values may be compressed and time-aligned to the historian's clock, which drifts from the DCS clock. Workflows that depend on event ordering must call `evidence.get_soe` not `evidence.get_alarms`.

5. **Historian interpolation is explicit in the API.** Every historian read tool has a required `mode` parameter:
   - `mode=stored` — returns only archived points within the window. Empty list is a valid answer.
   - `mode=interpolated` — returns interpolated values; the response includes the interpolation method (linear, previous, step) and a flag on every value indicating whether it was stored or interpolated.
   - `mode=aggregated` — returns aggregates (avg, min, max, count) over sub-intervals; the response carries the aggregation method.
   The agent must never confuse these. Templates specify which mode to use per signal.

6. **Probe time window is a first-class object** with explicit semantics:
   ```python
   class TimeWindow(BaseModel):
       start: datetime    # UTC, required tzinfo
       end: datetime      # UTC, required tzinfo
       reference: Literal["trigger_time", "first_alarm", "last_normal"]
       lookback: timedelta
       lookahead: timedelta
   ```
   Tools that pull evidence over the window honor it; tools that pull "current state" make that explicit in their name (`maximo.get_open_workorders_now`).

7. **All durations and intervals are timedelta**, not floats with implicit unit. Pydantic models enforce.

## Alternatives considered

**A. Store timestamps as Unix epoch integers.** Rejected — loses subsecond precision unless we use nanoseconds, and creates more conversion surface. ISO 8601 is human-readable in logs and traces.

**B. Local time with explicit TZ string.** Rejected — every join operation requires conversion. UTC-everywhere eliminates an entire class of bugs.

**C. Implicit interpolation in historian tools.** Rejected — this is exactly how false transients get introduced into agent reasoning.

**D. Trust each source's timestamps without observed offset measurements.** Rejected — clock skew is real and we have seen it cause RCA misordering in practice. The cost of measuring offset at ingest is small; the cost of getting sequence wrong is large.

## Consequences

**Positive:**

- All cross-source joins are unambiguous.
- Sequence-of-events ordering uses the right data source by policy.
- Interpolation can never silently mislead the agent — the tool API forces a choice.
- Clock skew is visible in every evidence bundle; reviewers can spot suspicious ordering.

**Negative:**

- Connector implementations are heavier — every connector must include TZ normalization and offset measurement.
- Engineers reading raw evidence bundles see UTC, which is unfamiliar; UI converts to local for display.
- Maximo and similar local-time-without-TZ sources require per-tenant configuration; getting this wrong silently mis-aligns historical data.

## References

- [SPEC-001 Evidence Bundle](../foundations/SPEC-001-evidence-bundle.md)
- [SPEC-002 MCP Tool Contracts](../connectors/SPEC-002-mcp-tool-contracts.md) — historian tool API
- ISO 8601: https://www.iso.org/iso-8601-date-and-time-format.html
- IANA TZ database: https://www.iana.org/time-zones
