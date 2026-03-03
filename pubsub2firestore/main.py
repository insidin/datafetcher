"""Cloud Run service that pulls from a Pub/Sub subscription and writes to Firestore.

Data model in Firestore:
  /state/{topic_key}                      — overwritten on every message; current state per MQTT topic
  /readings/{event_type}/{message_id}     — appended; time-series per event type, TTL-based cleanup
"""

import json
import logging
import os
import signal
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

from google.api_core.exceptions import GoogleAPICallError
from google.cloud import firestore, pubsub_v1

LOGGER = logging.getLogger(__name__)

SUBSCRIPTION = os.environ["PUBSUB_SUBSCRIPTION"]
PROJECT_ID = os.environ["GCP_PROJECT_ID"]
TTL_DAYS = int(os.environ.get("TTL_DAYS", "30"))
PORT = int(os.environ.get("PORT", "8080"))


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


def process_message(
    message: pubsub_v1.types.PubsubMessage,
    db: firestore.Client,
) -> None:
    attributes = dict(message.attributes)
    event_type = attributes.get("event_type", "unknown")
    mqtt_topic = attributes.get("mqtt_topic", "")
    now = datetime.now(UTC)
    expires_at = now + timedelta(days=TTL_DAYS)

    try:
        payload = json.loads(message.data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = None  # binary MQTT payload — store as null

    doc = {
        "event_type": event_type,
        "mqtt_topic": mqtt_topic,
        "payload": payload,
        "attributes": attributes,
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
        {**doc, "published_at": now, "expires_at": expires_at},
    )


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    _start_health_server()
    LOGGER.info("Health server started on port %d", PORT)

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
