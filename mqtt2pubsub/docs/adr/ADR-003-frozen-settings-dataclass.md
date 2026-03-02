# ADR-003: Frozen Dataclass for Configuration

**Date:** 2024-01-01
**Status:** Accepted

## Context

All configuration is provided via environment variables. Configuration must be:
1. Validated early (fail-fast at startup, not mid-run).
2. Immutable after startup so background MQTT threads cannot inadvertently mutate it.
3. Easy to reason about — a single object capturing the entire runtime configuration.

Reading `os.environ` at call sites scattered throughout the codebase is error-prone, hard to test, and makes the full set of required variables non-obvious.

## Decision

Encapsulate all configuration in a `@dataclass(frozen=True)` named `Settings`:

- All environment variable reading and type coercion happens in `Settings.__init__` (via `__post_init__`).
- Validation (QoS range, mutually exclusive fields, numeric bounds) raises `ValueError` with clear messages.
- `frozen=True` makes instances immutable — reassigning any field after construction raises `FrozenInstanceError`.
- The single `Settings()` instance is constructed in `__main__` and passed to the forwarder constructor.

## Consequences

- **Positive:** Configuration errors surface immediately on startup with actionable messages.
- **Positive:** Immutability guarantees thread-safety for the configuration object.
- **Positive:** The full set of accepted environment variables is self-documenting in one place.
- **Negative:** `frozen=True` prevents defaults that reference other fields (worked around with `__post_init__`).
- **Rule:** No code outside `Settings` may call `os.environ.get` or `os.getenv`. All env-var access must be centralised there.
