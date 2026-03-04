"""Unit tests for pubsub2firestore — no GCP credentials required."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from google.api_core.exceptions import NotFound

from main import _topic_key, _update_diagnostics, process_message

# ── _topic_key ────────────────────────────────────────────────────────────────


def test_topic_key_normalises_slashes():
    assert _topic_key("shellyhtg3-abc/status/temperature:0") == (
        "shellyhtg3-abc_status_temperature_0"
    )


def test_topic_key_normalises_colons():
    assert _topic_key("device/switch:0") == "device_switch_0"


def test_topic_key_strips_leading_trailing_underscores():
    assert _topic_key("/leading") == "leading"


def test_topic_key_empty_string_returns_unknown():
    assert _topic_key("") == "unknown"


# ── _update_diagnostics ───────────────────────────────────────────────────────


def test_update_diagnostics_updates_existing_doc():
    db = MagicMock()
    ref = MagicMock()
    db.collection.return_value.document.return_value = ref
    now = datetime.now(UTC)

    _update_diagnostics("shellyhtg3-abc", "status_temperature_0", {"tC": 20.5}, now, db)

    ref.update.assert_called_once()
    updates = ref.update.call_args[0][0]
    assert updates["last_seen"] == now
    assert updates["message_types.status_temperature_0.last_seen"] == now
    assert updates["message_types.status_temperature_0.last_payload"] == {"tC": 20.5}


def test_update_diagnostics_sets_on_not_found():
    db = MagicMock()
    ref = MagicMock()
    db.collection.return_value.document.return_value = ref
    ref.update.side_effect = NotFound("not found")
    now = datetime.now(UTC)

    _update_diagnostics("shellyhtg3-abc", "online", True, now, db)

    ref.set.assert_called_once()
    doc = ref.set.call_args[0][0]
    assert doc["last_seen"] == now
    assert "online" in doc["message_types"]


# ── process_message ───────────────────────────────────────────────────────────


def _make_message(payload: object, attributes: dict) -> MagicMock:
    msg = MagicMock()
    msg.message_id = "msg-123"
    if payload is None:
        msg.data = b"\xff\xfe"
    elif isinstance(payload, bytes):
        msg.data = payload
    else:
        msg.data = json.dumps(payload).encode()
    msg.attributes = attributes
    return msg


def _make_wrapped_message(inner_payload: object, attributes: dict) -> MagicMock:
    """Simulate a message as produced by the new mqtt2pubsub (wrapped format)."""
    meta = {k: v for k, v in attributes.items() if k.startswith("event_")}
    outer = {"payload": inner_payload, "_meta": meta}
    return _make_message(outer, attributes)


def test_process_message_writes_state_and_reading():
    db = MagicMock()
    doc_ref = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    (
        db.collection.return_value.document.return_value.collection.return_value.document.return_value
    ) = doc_ref

    msg = _make_wrapped_message(
        {"tC": 20.5},
        {
            "event_type": "shellyhtg3_status_temperature_0",
            "event_device_uid": "shellyhtg3-abc",
            "event_message_type": "status_temperature_0",
            "mqtt_topic": "shellyhtg3-abc/status/temperature:0",
        },
    )

    with patch("main.MQTT_EVENT_TYPES", frozenset()):  # empty = allow all
        process_message(msg, db)

    # diagnostics + state + reading = 3 set calls
    assert doc_ref.set.call_count >= 2

    calls = [c[0][0] for c in doc_ref.set.call_args_list]
    state_call = next(c for c in calls if "updated_at" in c)
    reading_call = next(c for c in calls if "expires_at" in c)

    assert state_call["event_type"] == "shellyhtg3_status_temperature_0"
    assert state_call["payload"] == {"tC": 20.5}
    assert "expires_at" in reading_call
    assert "published_at" in reading_call


def test_process_message_unwraps_new_payload_format():
    db = MagicMock()
    doc_ref = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    (
        db.collection.return_value.document.return_value.collection.return_value.document.return_value
    ) = doc_ref

    msg = _make_wrapped_message(
        {"rh": 65.0},
        {
            "event_type": "shellyhtg3_status_humidity_0",
            "event_device_uid": "shellyhtg3-abc",
            "event_message_type": "status_humidity_0",
            "mqtt_topic": "shellyhtg3-abc/status/humidity:0",
        },
    )

    with patch("main.MQTT_EVENT_TYPES", frozenset()):
        process_message(msg, db)

    calls = [c[0][0] for c in doc_ref.set.call_args_list]
    state_call = next(c for c in calls if "updated_at" in c)
    assert state_call["payload"] == {"rh": 65.0}


def test_process_message_binary_payload_stores_none():
    db = MagicMock()
    doc_ref = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    (
        db.collection.return_value.document.return_value.collection.return_value.document.return_value
    ) = doc_ref

    msg = _make_message(
        None,
        {
            "event_type": "shellyhtg3_status_temperature_0",
            "event_device_uid": "shellyhtg3-abc",
            "event_message_type": "status_temperature_0",
            "mqtt_topic": "dev/raw",
        },
    )
    msg.data = b"\x00\x01\x02\xff"

    with patch("main.MQTT_EVENT_TYPES", frozenset()):
        process_message(msg, db)

    calls = [c[0][0] for c in doc_ref.set.call_args_list]
    state_call = next(c for c in calls if "updated_at" in c)
    assert state_call["payload"] is None


def test_process_message_filtered_event_type_skips_state_and_readings():
    """Messages not in MQTT_EVENT_TYPES still write diagnostics but skip state/readings."""
    db = MagicMock()
    doc_ref = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    (
        db.collection.return_value.document.return_value.collection.return_value.document.return_value
    ) = doc_ref
    diag_ref = MagicMock()
    db.collection.return_value.document.return_value = diag_ref

    msg = _make_wrapped_message(
        {"value": 1},
        {
            "event_type": "shellyhtg3_events_rpc",
            "event_device_uid": "shellyhtg3-abc",
            "event_message_type": "events_rpc",
            "mqtt_topic": "shellyhtg3-abc/events/rpc",
        },
    )

    allowed = frozenset(["shellyhtg3_status_temperature_0"])  # events_rpc NOT in set
    with patch("main.MQTT_EVENT_TYPES", allowed):
        process_message(msg, db)

    # diagnostics update should be called
    diag_ref.update.assert_called_once()
    # state set should NOT be called
    diag_ref.set.assert_not_called()


def test_process_message_no_mqtt_topic_uses_event_type_as_key():
    db = MagicMock()

    msg = _make_wrapped_message(
        {"value": 1},
        {
            "event_type": "custom_event",
            "event_device_uid": "mydev-abc",
            "event_message_type": "custom",
            "mqtt_topic": "",
        },
    )

    with patch("main.MQTT_EVENT_TYPES", frozenset()):
        process_message(msg, db)

    state_col = db.collection("state")
    document_keys = [c[0][0] for c in state_col.document.call_args_list]
    assert "custom_event" in document_keys
