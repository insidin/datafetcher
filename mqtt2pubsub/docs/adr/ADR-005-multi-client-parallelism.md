# ADR-005: Multi-Client MQTT Parallelism

**Date:** 2024-01-01
**Status:** Accepted

## Context

A single MQTT client connection may become a throughput bottleneck when subscribing to many device topics simultaneously, particularly on brokers that limit per-connection message rate.

The application may expand `DEVICE_IDENTIFIERS` into tens or hundreds of per-device topic filters. Distributing these across multiple independent MQTT client connections allows parallel consumption.

## Decision

Support a configurable number of MQTT client connections via `MQTT_CONSUMER_CLIENTS` (default: 1).

- Subscription filters (from `MQTT_TOPIC` or expanded `DEVICE_IDENTIFIERS`) are distributed across clients using **round-robin partitioning**.
- Each client runs an independent `paho-mqtt` network loop in a background thread (`loop_start()`).
- All clients share the same `PublishSink` instance (thread-safe via the underlying Pub/Sub client's internal batching).
- Message counting (`_processed_messages`) is protected by a `threading.Lock`.

## Consequences

- **Positive:** Linear throughput scaling for high-volume scenarios without changing application architecture.
- **Positive:** Failure of one client connection does not block others (individual retry logic per client).
- **Positive:** Zero-overhead in the default single-client case.
- **Negative:** Multiple connections consume more broker resources; MQTT brokers may have per-account connection limits.
- **Negative:** Round-robin partitioning does not account for message-rate imbalance across devices.
- **Rule:** All state accessed from multiple client callbacks must be protected by `threading.Lock`. Do not add shared mutable state without a lock.
