# ADR-006: Priority-Based Event Type Derivation

**Date:** 2024-01-01
**Status:** Accepted

## Context

Downstream Pub/Sub consumers benefit from a normalised `event_type` attribute that classifies each message (e.g., `telemetry`, `alarm`, `status`). This type may be encoded in:

- The MQTT topic structure (e.g., `devices/sensor-1/telemetry`).
- A field within the JSON payload (e.g., `{"event_type": "alarm", ...}`).
- A static mapping rule configured by the operator.

No single source is universally reliable across all device types and broker conventions, so a fallback strategy is needed.

## Decision

Derive `event_type` using a **four-level priority cascade**:

| Priority | Source | Mechanism |
|---|---|---|
| 1 (highest) | `EVENT_TYPE_TOPIC_MAP` | Operator-configured MQTT-filter-to-event-type rules; evaluated first |
| 2 | Topic structure | Segment after the device identifier in identifier-expansion mode |
| 3 | Payload JSON field | First matching field from `EVENT_TYPE_JSON_FIELDS` list |
| 4 (fallback) | `EVENT_TYPE_FALLBACK` | Static default (defaults to `"unknown"`) |

The derived value is normalised (lowercase, non-alphanumeric characters replaced with `_`) before being set as a Pub/Sub attribute. A companion attribute `event_type_source` records which priority level was used.

## Consequences

- **Positive:** Operators can override event type for any topic pattern without code changes.
- **Positive:** Works out-of-the-box for common MQTT conventions (topic-segment and payload-field approaches).
- **Positive:** `event_type_source` makes derivation transparent and debuggable.
- **Negative:** Four levels of logic add complexity — operators must understand priority ordering.
- **Negative:** Payload JSON parsing adds a small overhead per message; skipped if payload is not valid JSON.
- **Rule:** The priority order must not change without a new ADR and a `BREAKING CHANGE` note in the commit, as downstream consumers may depend on the current behaviour.
