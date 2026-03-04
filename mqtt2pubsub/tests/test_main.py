"""Unit tests for main.py — no GCP or MQTT broker required."""

import json
import os
import sys

import pytest

# main.py lives one directory above this file
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import main  # noqa: E402, I001


# ---------------------------------------------------------------------------
# _parse_mqtt_topic
# ---------------------------------------------------------------------------


class TestParseMqttTopic:
    def test_standard_status_topic(self):
        result = main._parse_mqtt_topic("shellyplugsg3-e4b063e59f78/status/switch:0")
        assert result == {
            "event_type": "shellyplugsg3_status_switch_0",
            "event_device_uid": "shellyplugsg3-e4b063e59f78",
            "event_device_type": "shellyplugsg3",
            "event_device_id": "e4b063e59f78",
            "event_message_type": "status_switch_0",
        }

    def test_temperature_topic(self):
        result = main._parse_mqtt_topic("shellyhtg3-80b54e338948/status/temperature:0")
        assert result is not None
        assert result["event_type"] == "shellyhtg3_status_temperature_0"
        assert result["event_device_uid"] == "shellyhtg3-80b54e338948"
        assert result["event_device_type"] == "shellyhtg3"
        assert result["event_device_id"] == "80b54e338948"
        assert result["event_message_type"] == "status_temperature_0"

    def test_online_topic(self):
        result = main._parse_mqtt_topic("shellyhtg3-abc123/online")
        assert result is not None
        assert result["event_type"] == "shellyhtg3_online"
        assert result["event_message_type"] == "online"

    def test_events_rpc_topic(self):
        result = main._parse_mqtt_topic("shellyhtg3-abc123/events/rpc")
        assert result is not None
        assert result["event_type"] == "shellyhtg3_events_rpc"
        assert result["event_message_type"] == "events_rpc"

    def test_no_slash_returns_none(self):
        assert main._parse_mqtt_topic("noslash") is None

    def test_no_dash_in_device_returns_none(self):
        assert main._parse_mqtt_topic("deviceonly/status") is None

    def test_empty_message_path_returns_none(self):
        assert main._parse_mqtt_topic("shellyhtg3-abc/") is None

    def test_device_id_with_dashes(self):
        # device_id may contain dashes — only the first dash separates type from id
        result = main._parse_mqtt_topic("mydevice-a1-b2-c3/status")
        assert result is not None
        assert result["event_device_type"] == "mydevice"
        assert result["event_device_id"] == "a1-b2-c3"
        assert result["event_device_uid"] == "mydevice-a1-b2-c3"


# ---------------------------------------------------------------------------
# _inject_meta
# ---------------------------------------------------------------------------


class TestInjectMeta:
    def test_json_payload_wrapped(self):
        meta = {
            "event_type": "test",
            "event_device_uid": "dev-1",
            "event_device_type": "dev",
            "event_device_id": "1",
            "event_message_type": "status",
        }
        result = json.loads(main._inject_meta(b'{"tC": 20.5}', meta))
        assert result["payload"] == {"tC": 20.5}
        assert result["_meta"]["event_type"] == "test"

    def test_boolean_json_payload(self):
        meta = {
            "event_type": "t",
            "event_device_uid": "d",
            "event_device_type": "d",
            "event_device_id": "d",
            "event_message_type": "online",
        }
        result = json.loads(main._inject_meta(b"true", meta))
        assert result["payload"] is True

    def test_binary_payload_stored_as_null(self):
        meta = {
            "event_type": "t",
            "event_device_uid": "d",
            "event_device_type": "d",
            "event_device_id": "d",
            "event_message_type": "raw",
        }
        result = json.loads(main._inject_meta(b"\x00\x01\xff", meta))
        assert result["payload"] is None

    def test_output_is_valid_utf8_json(self):
        meta = {
            "event_type": "x",
            "event_device_uid": "x",
            "event_device_type": "x",
            "event_device_id": "x",
            "event_message_type": "x",
        }
        out = main._inject_meta(b'{"a":1}', meta)
        assert isinstance(out, bytes)
        json.loads(out.decode("utf-8"))  # must not raise


# ---------------------------------------------------------------------------
# _parse_device_identifiers
# ---------------------------------------------------------------------------


class TestParseDeviceIdentifiers:
    def test_single(self):
        assert main._parse_device_identifiers("dev1") == ("dev1",)

    def test_multiple(self):
        assert main._parse_device_identifiers("dev1,dev2,dev3") == ("dev1", "dev2", "dev3")

    def test_strips_whitespace(self):
        assert main._parse_device_identifiers("dev1 , dev2 ") == ("dev1", "dev2")

    def test_empty_string(self):
        assert main._parse_device_identifiers("") == ()

    def test_wildcard_plus_raises(self):
        with pytest.raises(ValueError, match="wildcard"):
            main._parse_device_identifiers("dev+1")

    def test_wildcard_hash_raises(self):
        with pytest.raises(ValueError, match="wildcard"):
            main._parse_device_identifiers("dev#1")


# ---------------------------------------------------------------------------
# _build_subscription_filters
# ---------------------------------------------------------------------------


class TestBuildSubscriptionFilters:
    def test_single_topic(self):
        result = main._build_subscription_filters("sensors/#", (), "{identifier}/#")
        assert result == ("sensors/#",)

    def test_device_identifiers_override_topic(self):
        result = main._build_subscription_filters("sensors/#", ("dev1", "dev2"), "{identifier}/#")
        assert result == ("dev1/#", "dev2/#")

    def test_custom_template(self):
        result = main._build_subscription_filters(None, ("abc",), "home/{identifier}/state")
        assert result == ("home/abc/state",)

    def test_no_topic_no_identifiers_raises(self):
        with pytest.raises(ValueError):
            main._build_subscription_filters(None, (), "{identifier}/#")

    def test_template_without_placeholder_raises(self):
        with pytest.raises(ValueError, match="\\{identifier\\}"):
            main._build_subscription_filters(None, ("dev1",), "no_placeholder/#")


# ---------------------------------------------------------------------------
# _partition_filters
# ---------------------------------------------------------------------------


class TestPartitionFilters:
    def test_single_client_all_filters(self):
        result = main._partition_filters(("a", "b", "c"), 1)
        assert result == (("a", "b", "c"),)

    def test_equal_split(self):
        result = main._partition_filters(("a", "b"), 2)
        assert result == (("a",), ("b",))

    def test_round_robin(self):
        result = main._partition_filters(("a", "b", "c"), 2)
        assert result == (("a", "c"), ("b",))

    def test_more_clients_than_filters(self):
        result = main._partition_filters(("a",), 5)
        assert result == (("a",),)

    def test_zero_clients_raises(self):
        with pytest.raises(ValueError, match=">="):
            main._partition_filters(("a",), 0)


# ---------------------------------------------------------------------------
# Settings.from_env  (stdout mode — no GCP credentials required)
# ---------------------------------------------------------------------------


class TestSettingsFromEnv:
    def _base_env(self, monkeypatch):
        monkeypatch.setenv("FORWARD_MODE", "stdout")
        monkeypatch.setenv("MQTT_HOST", "localhost")
        monkeypatch.setenv("MQTT_TOPIC", "test/#")
        # Clear variables that might linger from a real environment
        for var in (
            "PUBSUB_TOPIC",
            "GCP_PROJECT_ID",
            "GOOGLE_CLOUD_PROJECT",
            "MQTT_QOS",
            "MQTT_CONSUMER_CLIENTS",
            "DEVICE_IDENTIFIERS",
        ):
            monkeypatch.delenv(var, raising=False)

    def test_minimal_stdout_mode(self, monkeypatch):
        self._base_env(monkeypatch)
        s = main.Settings.from_env()
        assert s.forward_mode == "stdout"
        assert s.mqtt_host == "localhost"
        assert s.mqtt_subscription_filters == ("test/#",)

    def test_missing_mqtt_host_raises(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.delenv("MQTT_HOST")
        with pytest.raises(ValueError, match="MQTT_HOST"):
            main.Settings.from_env()

    def test_missing_both_topic_and_identifiers_raises(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.delenv("MQTT_TOPIC")
        with pytest.raises(ValueError):
            main.Settings.from_env()

    def test_pubsub_mode_missing_pubsub_topic_raises(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.setenv("FORWARD_MODE", "pubsub")
        monkeypatch.setenv("GCP_PROJECT_ID", "my-project")
        monkeypatch.delenv("PUBSUB_TOPIC", raising=False)
        with pytest.raises(ValueError, match="PUBSUB_TOPIC"):
            main.Settings.from_env()

    def test_invalid_forward_mode_raises(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.setenv("FORWARD_MODE", "kafka")
        with pytest.raises(ValueError, match="FORWARD_MODE"):
            main.Settings.from_env()

    def test_invalid_qos_raises(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.setenv("MQTT_QOS", "3")
        with pytest.raises(ValueError, match="MQTT_QOS"):
            main.Settings.from_env()

    def test_device_identifiers_expand_to_filters(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.delenv("MQTT_TOPIC")
        monkeypatch.setenv("DEVICE_IDENTIFIERS", "dev1,dev2")
        monkeypatch.setenv("MQTT_TOPIC_TEMPLATE", "{identifier}/state")
        s = main.Settings.from_env()
        assert s.mqtt_subscription_filters == ("dev1/state", "dev2/state")

    def test_device_identifiers_with_empty_template_uses_default(self, monkeypatch):
        # Regression: MQTT_TOPIC_TEMPLATE set to "" must fall back to "{identifier}/#"
        self._base_env(monkeypatch)
        monkeypatch.delenv("MQTT_TOPIC")
        monkeypatch.setenv("DEVICE_IDENTIFIERS", "dev1,dev2")
        monkeypatch.setenv("MQTT_TOPIC_TEMPLATE", "")
        s = main.Settings.from_env()
        assert s.mqtt_subscription_filters == ("dev1/#", "dev2/#")

    def test_consumer_clients_partition(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.delenv("MQTT_TOPIC")
        monkeypatch.setenv("DEVICE_IDENTIFIERS", "a,b,c")
        monkeypatch.setenv("MQTT_CONSUMER_CLIENTS", "2")
        s = main.Settings.from_env()
        assert len(s.mqtt_filter_groups) == 2
