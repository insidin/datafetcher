# ADR-002: PublishSink Protocol for Output Abstraction

**Date:** 2024-01-01
**Status:** Accepted

## Context

The application must publish MQTT messages somewhere — initially Google Cloud Pub/Sub. However, local development and testing without GCP credentials should be possible, and future destinations (e.g., alternative message brokers, HTTP webhooks) should not require changes to the core routing logic.

Coupling `MqttToPubSubForwarder` directly to the Pub/Sub client would make testing harder and reduce extensibility.

## Decision

Define a `PublishSink` **structural protocol** (PEP 544 / `typing.Protocol`) with a single required method:

```python
class PublishSink(Protocol):
    def publish(self, topic: str, payload: bytes, attributes: dict[str, str]) -> None: ...
```

Concrete implementations:
- `PubSubSink` — production: forwards to Google Cloud Pub/Sub.
- `StdoutSink` — development/debug: prints to stdout and optionally writes NDJSON to a local file.

The `MqttToPubSubForwarder` depends only on the protocol, not on any concrete class. The correct sink is instantiated in `__main__` based on the `FORWARD_MODE` environment variable.

## Consequences

- **Positive:** Core logic is testable without any GCP credentials — run with `FORWARD_MODE=stdout`.
- **Positive:** New destinations can be added by implementing the protocol without touching the forwarder.
- **Positive:** Structural (duck-typed) protocol keeps the code Pythonic — no explicit inheritance required.
- **Negative:** Protocol correctness is enforced only by type checkers (e.g., mypy), not at runtime.
- **Follow-up:** If a third sink is ever added, consider a factory function to centralise `FORWARD_MODE` dispatch.
