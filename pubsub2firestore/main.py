"""Cloud Run service that pulls from a Pub/Sub subscription and writes to Firestore.

Data model in Firestore:
  /state/{topic_key}              overwritten on every message; current state per MQTT topic
  /readings/{event_type}/...      appended for configured event types only; TTL-based cleanup
  /diagnostics/{device_uid}       updated for every message; last-seen + per-message-type data
"""

import json
import logging
import os
import signal
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.cloud import firestore, pubsub_v1

LOGGER = logging.getLogger(__name__)

SUBSCRIPTION = os.environ["PUBSUB_SUBSCRIPTION"]
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
TTL_DAYS = int(os.environ.get("TTL_DAYS", "30"))
PORT = int(os.environ.get("PORT", "8080"))

# Comma-separated list of event_types that get written to state + readings.
# Empty = write all event types (backwards-compatible default).
_raw_event_types = os.environ.get("MQTT_EVENT_TYPES", "").strip()
MQTT_EVENT_TYPES: frozenset[str] = frozenset(
    t.strip() for t in _raw_event_types.split(",") if t.strip()
)


# ── Health server ────────────────────────────────────────────────────────────


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *_args: object) -> None:
        pass  # suppress per-request access logs


def _start_health_server() -> HTTPServer:
    server = HTTPServer(("", PORT), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


# ── Message processing ───────────────────────────────────────────────────────


def _topic_key(mqtt_topic: str) -> str:
    """Normalise an MQTT topic string to a valid Firestore document ID."""
    return mqtt_topic.replace("/", "_").replace(":", "_").strip("_") or "unknown"


def _update_diagnostics(
    device_uid: str,
    message_type: str,
    payload: object,
    now: datetime,
    db: firestore.Client,
) -> None:
    """Update /diagnostics/{device_uid} with last-seen info for this message type."""
    ref = db.collection("diagnostics").document(device_uid)
    updates = {
        "last_seen": now,
        f"message_types.{message_type}.last_seen": now,
        f"message_types.{message_type}.last_payload": payload,
    }
    try:
        ref.update(updates)
    except NotFound:
        ref.set(
            {
                "last_seen": now,
                "message_types": {
                    message_type: {"last_seen": now, "last_payload": payload},
                },
            }
        )


def process_message(
    message: pubsub_v1.types.PubsubMessage,
    db: firestore.Client,
) -> None:
    attributes = dict(message.attributes)
    event_type = attributes.get("event_type", "unknown")
    mqtt_topic = attributes.get("mqtt_topic", "")
    device_uid = attributes.get("event_device_uid", "")
    message_type = attributes.get("event_message_type", "")
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=TTL_DAYS)
    publish_time = message.publish_time  # Pub/Sub publish timestamp

    # Unwrap payload: mqtt2pubsub wraps as {"payload": <original>, "_meta": {...}}.
    # Older messages or non-standard sources may not have this wrapper.
    try:
        outer = json.loads(message.data.decode("utf-8"))
        if isinstance(outer, dict) and "payload" in outer and "_meta" in outer:
            payload = outer["payload"]
        else:
            payload = outer
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None  # binary MQTT payload — store as null

    # Diagnostics: written for every message, regardless of MQTT_EVENT_TYPES.
    if device_uid and message_type:
        _update_diagnostics(device_uid, message_type, payload, now, db)

    # State + readings: written only for configured event types (or all if not configured).
    if MQTT_EVENT_TYPES and event_type not in MQTT_EVENT_TYPES:
        return

    doc = {
        "event_type": event_type,
        "mqtt_topic": mqtt_topic,
        "payload": payload,
        "attributes": attributes,
        "message_id": message.message_id,
        "publish_time": publish_time,
    }

    # 1. Overwrite current state — one document per MQTT topic for live display.
    state_key = _topic_key(mqtt_topic) if mqtt_topic else event_type
    db.collection("state").document(state_key).set(
        {**doc, "updated_at": now},
    )

    # 2. Append to time-series — one document per message for chart queries.
    db.collection("readings").document(event_type).collection("messages").document(
        message.message_id
    ).set(
        {**doc, "published_at": publish_time, "expires_at": expires_at},
    )


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    _start_health_server()
    LOGGER.info("Health server started on port %d", PORT)
    LOGGER.info(
        "MQTT_EVENT_TYPES filter: %s",
        sorted(MQTT_EVENT_TYPES) if MQTT_EVENT_TYPES else "(all)",
    )

    db = firestore.Client(project=PROJECT_ID)
    subscriber = pubsub_v1.SubscriberClient()

    def callback(message: pubsub_v1.types.PubsubMessage) -> None:
        try:
            process_message(message, db)
            message.ack()
            LOGGER.debug(
                "ACKed message_id=%s event_type=%s",
                message.message_id,
                message.attributes.get("event_type"),
            )
        except GoogleAPICallError:
            LOGGER.exception(
                "Firestore error for message_id=%s — NACKing for retry",
                message.message_id,
            )
            message.nack()
        except Exception:
            LOGGER.exception(
                "Unexpected error for message_id=%s — NACKing",
                message.message_id,
            )
            message.nack()

    streaming_pull = subscriber.subscribe(SUBSCRIPTION, callback=callback)
    LOGGER.info("Listening for messages on %s", SUBSCRIPTION)

    stop_event = threading.Event()

    def _shutdown(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %d, shutting down...", signum)
        streaming_pull.cancel()
        stop_event.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        stop_event.wait()
        streaming_pull.result(timeout=10)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
