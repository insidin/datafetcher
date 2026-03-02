#!/usr/bin/env python3
"""MQTT -> Pub/Sub forwarder for Cloud Run Jobs or local testing."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import paho.mqtt.client as mqtt
from google.cloud import pubsub_v1


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Environment variable {name} must be boolean, got {raw!r}")


def _env_csv(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _mqtt_topic_matches(topic_filter: str, topic: str) -> bool:
    """Match MQTT topic with MQTT filter syntax (+ and # wildcards)."""
    filter_levels = topic_filter.split("/")
    topic_levels = topic.split("/")
    idx_filter = 0
    idx_topic = 0

    while idx_filter < len(filter_levels):
        filter_level = filter_levels[idx_filter]

        if filter_level == "#":
            return idx_filter == len(filter_levels) - 1

        if idx_topic >= len(topic_levels):
            return False

        if filter_level != "+" and filter_level != topic_levels[idx_topic]:
            return False

        idx_filter += 1
        idx_topic += 1

    return idx_topic == len(topic_levels)


_EVENT_TYPE_SAFE_RE = re.compile(r"[^a-z0-9_.-]+")


def _normalize_event_type(value: str, fallback: str) -> str:
    normalized = _EVENT_TYPE_SAFE_RE.sub("_", value.strip().lower()).strip("._-")
    if normalized:
        return normalized
    return fallback


def _parse_event_type_topic_map(raw: str, fallback: str) -> tuple[tuple[str, str], ...]:
    if not raw.strip():
        return ()

    rules: list[tuple[str, str]] = []
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(
                f"EVENT_TYPE_TOPIC_MAP entries must be in '<mqtt_filter>=<event_type>' format, got {item!r}"
            )
        topic_filter, event_type = item.split("=", 1)
        topic_filter = topic_filter.strip()
        event_type = _normalize_event_type(event_type, fallback)
        if not topic_filter:
            raise ValueError(f"EVENT_TYPE_TOPIC_MAP has empty topic filter in entry {item!r}")
        rules.append((topic_filter, event_type))

    return tuple(rules)


def _parse_device_identifiers(raw: str) -> tuple[str, ...]:
    identifiers = []
    for item in raw.split(","):
        identifier = item.strip()
        if not identifier:
            continue
        if "+" in identifier or "#" in identifier:
            raise ValueError(
                f"Invalid DEVICE_IDENTIFIERS value {identifier!r}: wildcard characters '+' and '#' are not allowed"
            )
        identifiers.append(identifier)
    return tuple(identifiers)


def _build_subscription_filters(
    mqtt_topic: str | None,
    device_identifiers: tuple[str, ...],
    mqtt_topic_template: str,
) -> tuple[str, ...]:
    if device_identifiers:
        if "{identifier}" not in mqtt_topic_template:
            raise ValueError("MQTT_TOPIC_TEMPLATE must contain '{identifier}' when DEVICE_IDENTIFIERS is set")
        return tuple(mqtt_topic_template.replace("{identifier}", identifier) for identifier in device_identifiers)

    if mqtt_topic:
        return (mqtt_topic,)

    raise ValueError("Set MQTT_TOPIC, or set DEVICE_IDENTIFIERS to derive topic filters")


def _partition_filters(filters: tuple[str, ...], clients: int) -> tuple[tuple[str, ...], ...]:
    if clients <= 0:
        raise ValueError("MQTT_CONSUMER_CLIENTS must be >= 1")
    groups = [[] for _ in range(min(clients, len(filters)))]
    for idx, topic_filter in enumerate(filters):
        groups[idx % len(groups)].append(topic_filter)
    return tuple(tuple(group) for group in groups if group)


class PublishSink(Protocol):
    def publish(self, payload: bytes, attributes: dict[str, str]) -> str: ...

    def describe(self) -> str: ...


class PubSubSink:
    def __init__(self, project_id: str, topic: str, timeout_sec: int) -> None:
        self.publisher = pubsub_v1.PublisherClient()
        self.topic_path = topic if topic.startswith("projects/") else self.publisher.topic_path(project_id, topic)
        self.timeout_sec = timeout_sec

    def publish(self, payload: bytes, attributes: dict[str, str]) -> str:
        publish_future = self.publisher.publish(self.topic_path, payload, **attributes)
        return publish_future.result(timeout=self.timeout_sec)

    def describe(self) -> str:
        return self.topic_path


class StdoutSink:
    def __init__(self, output_path: str | None) -> None:
        self._counter = 0
        self.output_path = Path(output_path) if output_path else None
        if self.output_path:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)

    def publish(self, payload: bytes, attributes: dict[str, str]) -> str:
        self._counter += 1
        message_id = f"local-{self._counter}"
        record = {
            "message_id": message_id,
            "payload_utf8": payload.decode("utf-8", errors="replace"),
            "payload_base64": base64.b64encode(payload).decode("ascii"),
            "attributes": attributes,
        }
        line = json.dumps(record, sort_keys=True, separators=(",", ":"))
        logging.info("LOCAL_FORWARD %s", line)

        if self.output_path:
            with self.output_path.open("a", encoding="utf-8") as fp:
                fp.write(line + "\n")

        return message_id

    def describe(self) -> str:
        if self.output_path:
            return f"stdout + {self.output_path}"
        return "stdout"


@dataclass(frozen=True)
class Settings:
    forward_mode: str
    mqtt_host: str
    mqtt_port: int
    mqtt_topic: str | None
    mqtt_topic_template: str
    mqtt_subscription_filters: tuple[str, ...]
    mqtt_consumer_clients: int
    mqtt_filter_groups: tuple[tuple[str, ...], ...]
    device_identifiers: tuple[str, ...]
    mqtt_qos: int
    mqtt_keepalive: int
    mqtt_client_id: str
    mqtt_username: str | None
    mqtt_password: str | None
    mqtt_tls_enabled: bool
    mqtt_tls_ca_cert: str | None
    mqtt_tls_insecure: bool
    pubsub_topic: str | None
    gcp_project_id: str
    pubsub_publish_timeout_sec: int
    pubsub_publish_retries: int
    max_messages: int
    max_runtime_sec: int
    local_output_path: str | None
    event_type_topic_map: tuple[tuple[str, str], ...]
    event_type_json_fields: tuple[str, ...]
    event_type_fallback: str

    @classmethod
    def from_env(cls) -> Settings:
        forward_mode = os.getenv("FORWARD_MODE", "pubsub").strip().lower()
        if forward_mode not in {"pubsub", "stdout"}:
            raise ValueError(f"FORWARD_MODE must be one of pubsub|stdout, got {forward_mode!r}")

        project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
        pubsub_topic_raw = os.getenv("PUBSUB_TOPIC", "").strip()
        mqtt_topic_raw = os.getenv("MQTT_TOPIC", "").strip() or None
        # Use `or` so an empty string (e.g. from an unset GitHub secret that
        # Terraform passes as "") falls back to the default, same as if the
        # variable were absent entirely.
        mqtt_topic_template = (os.getenv("MQTT_TOPIC_TEMPLATE") or "{identifier}/#").strip()
        device_identifiers = _parse_device_identifiers(os.getenv("DEVICE_IDENTIFIERS", ""))
        mqtt_subscription_filters = _build_subscription_filters(
            mqtt_topic=mqtt_topic_raw,
            device_identifiers=device_identifiers,
            mqtt_topic_template=mqtt_topic_template,
        )
        mqtt_consumer_clients = _env_int("MQTT_CONSUMER_CLIENTS", 1)
        mqtt_filter_groups = _partition_filters(mqtt_subscription_filters, mqtt_consumer_clients)

        if forward_mode == "pubsub":
            if not pubsub_topic_raw:
                raise ValueError("Missing required environment variable: PUBSUB_TOPIC")
            if not project_id and not pubsub_topic_raw.startswith("projects/"):
                raise ValueError(
                    "Set GCP_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) when PUBSUB_TOPIC is not a full "
                    "projects/.../topics/... path."
                )

        qos = _env_int("MQTT_QOS", 1)
        if qos not in (0, 1, 2):
            raise ValueError(f"MQTT_QOS must be one of 0, 1, 2; got {qos}")

        event_type_fallback = _normalize_event_type(os.getenv("EVENT_TYPE_FALLBACK", "unknown"), "unknown")
        event_type_topic_map = _parse_event_type_topic_map(
            os.getenv("EVENT_TYPE_TOPIC_MAP", ""),
            event_type_fallback,
        )
        event_type_json_fields = _env_csv("EVENT_TYPE_JSON_FIELDS", "event_type,type,kind")

        return cls(
            forward_mode=forward_mode,
            mqtt_host=_required_env("MQTT_HOST"),
            mqtt_port=_env_int("MQTT_PORT", 8883),
            mqtt_topic=mqtt_topic_raw,
            mqtt_topic_template=mqtt_topic_template,
            mqtt_subscription_filters=mqtt_subscription_filters,
            mqtt_consumer_clients=mqtt_consumer_clients,
            mqtt_filter_groups=mqtt_filter_groups,
            device_identifiers=device_identifiers,
            mqtt_qos=qos,
            mqtt_keepalive=_env_int("MQTT_KEEPALIVE_SEC", 60),
            mqtt_client_id=os.getenv("MQTT_CLIENT_ID", "mqtt2pubsub"),
            mqtt_username=os.getenv("MQTT_USERNAME"),
            mqtt_password=os.getenv("MQTT_PASSWORD"),
            mqtt_tls_enabled=_env_bool("MQTT_TLS_ENABLED", True),
            mqtt_tls_ca_cert=os.getenv("MQTT_TLS_CA_CERT") or None,
            mqtt_tls_insecure=_env_bool("MQTT_TLS_INSECURE", False),
            pubsub_topic=pubsub_topic_raw if pubsub_topic_raw else None,
            gcp_project_id=project_id,
            pubsub_publish_timeout_sec=_env_int("PUBSUB_PUBLISH_TIMEOUT_SEC", 30),
            pubsub_publish_retries=max(_env_int("PUBSUB_PUBLISH_RETRIES", 5), 1),
            max_messages=max(_env_int("MAX_MESSAGES", 0), 0),
            max_runtime_sec=max(_env_int("MAX_RUNTIME_SEC", 0), 0),
            local_output_path=os.getenv("LOCAL_OUTPUT_PATH") or None,
            event_type_topic_map=event_type_topic_map,
            event_type_json_fields=event_type_json_fields,
            event_type_fallback=event_type_fallback,
        )


class MqttToPubSubForwarder:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stop_event = threading.Event()
        self._fatal_exception: Exception | None = None
        self._state_lock = threading.Lock()
        self._started_at = time.monotonic()
        self._processed_messages = 0

        if self.settings.forward_mode == "pubsub":
            if not self.settings.pubsub_topic:
                raise RuntimeError("PUBSUB_TOPIC is required in pubsub mode")
            self.sink: PublishSink = PubSubSink(
                project_id=self.settings.gcp_project_id,
                topic=self.settings.pubsub_topic,
                timeout_sec=self.settings.pubsub_publish_timeout_sec,
            )
        else:
            self.sink = StdoutSink(self.settings.local_output_path)

        self.mqtt_clients: list[mqtt.Client] = []
        for idx, topic_filters in enumerate(self.settings.mqtt_filter_groups):
            if len(self.settings.mqtt_filter_groups) == 1:
                client_id = self.settings.mqtt_client_id
            else:
                client_id = f"{self.settings.mqtt_client_id}-{idx + 1}"

            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                clean_session=False,
                protocol=mqtt.MQTTv311,
            )
            client.user_data_set(
                {
                    "client_index": idx + 1,
                    "topic_filters": topic_filters,
                }
            )
            client.enable_logger(logging.getLogger(f"mqtt.client.{idx + 1}"))
            client.reconnect_delay_set(min_delay=1, max_delay=30)

            if self.settings.mqtt_username:
                client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)

            if self.settings.mqtt_tls_enabled:
                client.tls_set(ca_certs=self.settings.mqtt_tls_ca_cert)
                client.tls_insecure_set(self.settings.mqtt_tls_insecure)

            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.on_disconnect = self._on_disconnect
            self.mqtt_clients.append(client)

    def _set_fatal_exception(self, exc: Exception) -> None:
        with self._state_lock:
            if self._fatal_exception is None:
                self._fatal_exception = exc

    def _client_meta(self, userdata: object) -> tuple[int, tuple[str, ...]]:
        if isinstance(userdata, dict):
            idx = int(userdata.get("client_index", 0))
            topic_filters_raw = userdata.get("topic_filters", ())
            if isinstance(topic_filters_raw, tuple):
                return idx, topic_filters_raw
            if isinstance(topic_filters_raw, list):
                return idx, tuple(str(item) for item in topic_filters_raw)
        return 0, ()

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: object,
        flags: dict,
        reason_code: mqtt.ReasonCode,
        properties: object,
    ) -> None:
        client_index, topic_filters = self._client_meta(userdata)
        if reason_code.is_failure:
            # Log and return — do NOT stop the process. paho will reconnect
            # using reconnect_delay_set(), which is essential for Cloud Run Service
            # where the container must stay alive even when the broker is temporarily
            # unreachable or rejects credentials.
            logging.error(
                "MQTT client=%s rejected by broker: %s (will retry)",
                client_index or "?",
                reason_code,
            )
            return
        logging.info(
            "Connected MQTT client=%s to broker %s:%s",
            client_index or "?",
            self.settings.mqtt_host,
            self.settings.mqtt_port,
        )
        for topic_filter in topic_filters:
            result, _ = client.subscribe(topic_filter, qos=self.settings.mqtt_qos)
            if result != mqtt.MQTT_ERR_SUCCESS:
                self._set_fatal_exception(RuntimeError(f"Failed to subscribe to {topic_filter}, rc={result}"))
                self.stop_event.set()
                client.disconnect()
                return
            logging.info(
                "MQTT client=%s subscribed to %s with QoS %s",
                client_index or "?",
                topic_filter,
                self.settings.mqtt_qos,
            )

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: object,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: object,
    ) -> None:
        client_index, _ = self._client_meta(userdata)
        if self.stop_event.is_set():
            logging.info("MQTT client=%s disconnected cleanly", client_index or "?")
            return
        logging.warning("MQTT client=%s disconnected unexpectedly: %s", client_index or "?", reason_code)

    def _derive_event_type(self, message: mqtt.MQTTMessage) -> tuple[str, str]:
        for topic_filter, event_type in self.settings.event_type_topic_map:
            if _mqtt_topic_matches(topic_filter, message.topic):
                return event_type, f"topic_map:{topic_filter}"

        for identifier in self.settings.device_identifiers:
            prefix = f"{identifier}/"
            if message.topic.startswith(prefix):
                remainder = message.topic[len(prefix) :]
                if remainder:
                    event_segment = remainder.split("/", 1)[0]
                    event_type = _normalize_event_type(event_segment, self.settings.event_type_fallback)
                    return event_type, f"topic_after_identifier:{identifier}"

        try:
            payload_obj = json.loads(message.payload.decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload_obj = None

        if isinstance(payload_obj, dict):
            for field in self.settings.event_type_json_fields:
                field_value = payload_obj.get(field)
                if field_value is None:
                    continue
                if isinstance(field_value, str):
                    normalized = _normalize_event_type(field_value, self.settings.event_type_fallback)
                    return normalized, f"payload_field:{field}"
                if isinstance(field_value, (int, float, bool)):
                    normalized = _normalize_event_type(str(field_value), self.settings.event_type_fallback)
                    return normalized, f"payload_field:{field}"

        return self.settings.event_type_fallback, "fallback"

    def _publish(self, message: mqtt.MQTTMessage) -> str:
        event_type, event_type_source = self._derive_event_type(message)
        attributes = {
            "mqtt_topic": message.topic,
            "mqtt_qos": str(message.qos),
            "mqtt_retain": "1" if message.retain else "0",
            "mqtt_mid": str(message.mid),
            "received_at_utc": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "event_type_source": event_type_source,
        }
        return self.sink.publish(message.payload, attributes)

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: object,
        message: mqtt.MQTTMessage,
    ) -> None:
        last_error: Exception | None = None

        for attempt in range(1, self.settings.pubsub_publish_retries + 1):
            try:
                sink_message_id = self._publish(message)
                with self._state_lock:
                    self._processed_messages += 1
                    processed_messages = self._processed_messages
                logging.info(
                    "Forwarded MQTT message topic=%s mid=%s sink_message_id=%s",
                    message.topic,
                    message.mid,
                    sink_message_id,
                )
                if self.settings.max_messages and processed_messages >= self.settings.max_messages:
                    logging.info("Reached MAX_MESSAGES=%s, stopping", self.settings.max_messages)
                    self.stop()
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                backoff_sec = min(2 ** (attempt - 1), 30)
                logging.exception(
                    "Forward attempt %s/%s failed for topic=%s mid=%s",
                    attempt,
                    self.settings.pubsub_publish_retries,
                    message.topic,
                    message.mid,
                )
                if attempt < self.settings.pubsub_publish_retries:
                    time.sleep(backoff_sec)

        err = RuntimeError(
            f"Failed to forward MQTT message topic={message.topic} mid={message.mid} after "
            f"{self.settings.pubsub_publish_retries} attempts"
        )
        if last_error is not None:
            err.__cause__ = last_error
        self._set_fatal_exception(err)
        self.stop()

    def _connect_with_retry(self, client: mqtt.Client, client_index: int) -> None:
        """Keep trying client.connect() until it succeeds or stop_event is set.

        Runs in a daemon thread. Required because paho's automatic reconnect only
        kicks in after a successful initial connect; if the very first connect() call
        raises (DNS failure, connection refused, TLS error) paho won't retry on its
        own. Once the TCP connection is established, paho's reconnect_delay_set()
        handles all subsequent reconnects transparently.
        """
        delay = 1
        while not self.stop_event.is_set():
            try:
                client.connect(self.settings.mqtt_host, self.settings.mqtt_port, self.settings.mqtt_keepalive)
                return  # TCP connected — paho loop + reconnect_delay_set handles the rest
            except Exception:  # noqa: BLE001
                logging.exception(
                    "MQTT client=%s connect to %s:%s failed, retrying in %ss",
                    client_index,
                    self.settings.mqtt_host,
                    self.settings.mqtt_port,
                    delay,
                )
                self.stop_event.wait(delay)
                delay = min(delay * 2, 30)

    def start(self) -> None:
        logging.info(
            "Forward mode=%s destination=%s",
            self.settings.forward_mode,
            self.sink.describe(),
        )
        logging.info(
            "MQTT topic filters=%s consumer_clients=%s",
            list(self.settings.mqtt_subscription_filters),
            len(self.settings.mqtt_filter_groups),
        )
        for idx, client in enumerate(self.mqtt_clients):
            client_index = idx + 1 if len(self.mqtt_clients) > 1 else 1
            # Start the paho network loop before attempting to connect so it is
            # ready to handle the CONNACK when _connect_with_retry succeeds.
            client.loop_start()
            threading.Thread(
                target=self._connect_with_retry,
                args=(client, client_index),
                daemon=True,
                name=f"mqtt-connect-{client_index}",
            ).start()

    def stop(self) -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        for client in self.mqtt_clients:
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                logging.exception("Error while disconnecting MQTT client")

    def run(self) -> None:
        self.start()
        try:
            while not self.stop_event.is_set():
                if self.settings.max_runtime_sec:
                    elapsed = time.monotonic() - self._started_at
                    if elapsed >= self.settings.max_runtime_sec:
                        logging.info("Reached MAX_RUNTIME_SEC=%s, stopping", self.settings.max_runtime_sec)
                        self.stop()
                        break
                time.sleep(0.5)
        finally:
            if not self.stop_event.is_set():
                self.stop_event.set()
            for client in self.mqtt_clients:
                try:
                    client.disconnect()
                except Exception:  # noqa: BLE001
                    logging.exception("Error while disconnecting MQTT client")
                client.loop_stop()

        if self._fatal_exception:
            raise self._fatal_exception


def _configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _start_health_server() -> None:
    """Minimal HTTP server on $PORT so Cloud Run Service reports healthy."""
    import http.server

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass  # suppress access logs

    port = int(os.getenv("PORT", "8080"))
    server = http.server.HTTPServer(("", port), _Handler)
    server.serve_forever()


def main() -> int:
    _configure_logging()

    threading.Thread(target=_start_health_server, daemon=True).start()

    settings = Settings.from_env()
    forwarder = MqttToPubSubForwarder(settings)

    def _handle_shutdown(signum: int, frame: object) -> None:
        logging.info("Received signal %s, shutting down", signum)
        forwarder.stop()

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    forwarder.run()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        logging.exception("Fatal error: %s", exc)
        sys.exit(1)
