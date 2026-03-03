"""Unit tests for pubsub2firestore — no GCP credentials required."""

import json
from unittest.mock import MagicMock

from main import _topic_key, process_message

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


# ── process_message ───────────────────────────────────────────────────────────


def _make_message(payload: object, attributes: dict) -> MagicMock:
    msg = MagicMock()
    msg.message_id = "msg-123"
    msg.data = json.dumps(payload).encode() if payload is not None else b"\xff\xfe"
    msg.attributes = attributes
    return msg


def test_process_message_writes_state_and_reading():
    db = MagicMock()
    doc_ref = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    (
        db.collection.return_value.document.return_value.collection.return_value.document.return_value
    ) = doc_ref

    msg = _make_message(
        {"tC": 20.5},
        {"event_type": "shelly_temperature", "mqtt_topic": "dev/status/temperature:0"},
    )
    process_message(msg, db)

    assert doc_ref.set.call_count == 2

    calls = [c[0][0] for c in doc_ref.set.call_args_list]
    state_call = next(c for c in calls if "updated_at" in c)
    reading_call = next(c for c in calls if "expires_at" in c)

    assert state_call["event_type"] == "shelly_temperature"
    assert state_call["payload"] == {"tC": 20.5}
    assert "expires_at" in reading_call
    assert "published_at" in reading_call


def test_process_message_binary_payload_stores_none():
    db = MagicMock()
    doc_ref = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    (
        db.collection.return_value.document.return_value.collection.return_value.document.return_value
    ) = doc_ref

    msg = _make_message(None, {"event_type": "unknown", "mqtt_topic": "device/raw"})
    msg.data = b"\x00\x01\x02\xff"

    process_message(msg, db)

    state_kwargs = db.collection("state").document("device_raw").set.call_args[0][0]
    assert state_kwargs["payload"] is None


def test_process_message_no_mqtt_topic_uses_event_type_as_key():
    db = MagicMock()

    msg = _make_message({"value": 1}, {"event_type": "custom_event", "mqtt_topic": ""})

    process_message(msg, db)

    state_col = db.collection("state")
    document_keys = [c[0][0] for c in state_col.document.call_args_list]
    assert "custom_event" in document_keys
