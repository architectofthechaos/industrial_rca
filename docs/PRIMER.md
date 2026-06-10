# Explainers

These are conversational, narrative explanations of the system — written for a new engineer who needs to *understand* before they reference. They sit between the ADRs (which lock in decisions) and the specs (which define the implementation).

Read these first. Then go to the specs when you need the precise schema or algorithm.

## How explainers differ from specs

| | Explainer | Spec |
|---|---|---|
| Audience | New engineer, technical PM, curious onlooker | Implementing engineer |
| Style | Narrative, examples, "why this works" | Reference, terse, "what it is" |
| Stability | Updated as understanding improves | Stable once accepted; changes via PR |
| Length | Long-form OK | As short as possible while complete |
| Code | Illustrative snippets | Authoritative schemas |

## Available explainers

- [How TRS works](how-trs-works.md) — discovery, tag aliasing, matching algorithm, an end-to-end example
- [How the Master Asset Registry works](how-mar-works.md) — onboarding, canonical assets, why MAR before TRS
- [The probe lifecycle, end to end](probe-lifecycle.md) — *to be written*
- [Time, units, and provenance](time-units-provenance.md) — *to be written*
