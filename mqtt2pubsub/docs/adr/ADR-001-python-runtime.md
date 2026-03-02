# ADR-001: Python as Implementation Language

**Date:** 2024-01-01
**Status:** Accepted

## Context

The bridge needs a runtime that has mature, maintained client libraries for both MQTT (`paho-mqtt`) and Google Cloud Pub/Sub (`google-cloud-pubsub`). The application is primarily I/O-bound (network reads/writes) rather than CPU-bound, so raw execution speed is not a primary concern. The team is comfortable with Python and values readability and a rich ecosystem of GCP tooling.

## Decision

Use **Python 3.12** as the sole implementation language.

- `paho-mqtt` is the de-facto standard MQTT client for Python and directly supported by the Eclipse Foundation.
- `google-cloud-pubsub` is the official Google Cloud client library with full async/batch publish support.
- Python 3.12 ships `tomllib`, improved `typing`, and performance improvements over 3.11.
- The `python:3.12-slim` Docker base image keeps the container image small.

## Consequences

- **Positive:** Readable, concise code; large ecosystem; official GCP library support; type hints improve correctness.
- **Positive:** Fast iteration — single-file application with minimal boilerplate.
- **Negative:** Python's GIL limits true CPU parallelism, but the workload is I/O-bound and uses background threads only for MQTT network loops, so this is acceptable.
- **Negative:** Runtime errors not caught at compile time — mitigated by type hints and validation in `Settings`.
- **Follow-up:** Pin minor versions in `requirements.txt` to ensure reproducible builds.
