"""Unit tests for main.py — no GCP or MQTT broker required."""

import sys
import os

import pytest

# main.py lives one directory above this file
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import main  # noqa: E402


# ---------------------------------------------------------------------------
# _mqtt_topic_matches
# ---------------------------------------------------------------------------

class TestMqttTopicMatches:
    def test_exact_match(self):
        assert main._mqtt_topic_matches("a/b", "a/b")

    def test_no_match(self):
        assert not main._mqtt_topic_matches("a/b", "a/c")

    def test_extra_topic_level_no_match(self):
        assert not main._mqtt_topic_matches("a/b", "a/b/c")

    def test_single_level_wildcard_matches(self):
        assert main._mqtt_topic_matches("a/+", "a/b")

    def test_single_level_wildcard_no_extra(self):
        assert not main._mqtt_topic_matches("a/+", "a/b/c")

    def test_multi_level_wildcard_single(self):
        assert main._mqtt_topic_matches("a/#", "a/b")

    def test_multi_level_wildcard_deep(self):
        assert main._mqtt_topic_matches("a/#", "a/b/c/d")

    def test_multi_level_wildcard_wrong_prefix(self):
        assert not main._mqtt_topic_matches("a/#", "b/c")

    def test_hash_only(self):
        assert main._mqtt_topic_matches("#", "anything/at/all")

    def test_hash_not_last_no_match(self):
        # '#' must be the last segment to match; mid-filter '#' returns False
        assert not main._mqtt_topic_matches("a/#/c", "a/b/c")

    def test_mixed_wildcards(self):
        assert main._mqtt_topic_matches("+/+/#", "x/y/z/w")


# ---------------------------------------------------------------------------
# _normalize_event_type
# ---------------------------------------------------------------------------

class TestNormalizeEventType:
    def test_lowercases(self):
        assert main._normalize_event_type("Temperature", "unknown") == "temperature"

    def test_replaces_spaces(self):
        assert main._normalize_event_type("my event", "unknown") == "my_event"

    def test_allowed_chars_preserved(self):
        assert main._normalize_event_type("my-event.type_1", "unknown") == "my-event.type_1"

    def test_strips_leading_trailing_separators(self):
        assert main._normalize_event_type("...type...", "unknown") == "type"

    def test_empty_returns_fallback(self):
        assert main._normalize_event_type("", "unknown") == "unknown"

    def test_only_special_chars_returns_fallback(self):
        assert main._normalize_event_type("!!!---", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# _parse_event_type_topic_map
# ---------------------------------------------------------------------------

class TestParseEventTypeTopicMap:
    def test_empty_string(self):
        assert main._parse_event_type_topic_map("", "unknown") == ()

    def test_whitespace_only(self):
        assert main._parse_event_type_topic_map("   ", "unknown") == ()

    def test_single_rule(self):
        result = main._parse_event_type_topic_map("sensors/+/temp=temperature", "unknown")
        assert result == (("sensors/+/temp", "temperature"),)

    def test_multiple_rules(self):
        result = main._parse_event_type_topic_map("a/#=TypeA;b/#=typeB", "unknown")
        assert result == (("a/#", "typea"), ("b/#", "typeb"))

    def test_normalises_event_type(self):
        result = main._parse_event_type_topic_map("t/#=My Event Type", "unknown")
        assert result == (("t/#", "my_event_type"),)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="must be in"):
            main._parse_event_type_topic_map("no_equals_sign", "unknown")

    def test_empty_topic_filter_raises(self):
        with pytest.raises(ValueError, match="empty topic filter"):
            main._parse_event_type_topic_map("=some_event", "unknown")

    def test_skips_empty_segments(self):
        result = main._parse_event_type_topic_map("a/#=typeA;;b/#=typeB;", "unknown")
        assert result == (("a/#", "typea"), ("b/#", "typeb"))


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
        # Only one group is created when clients > filters
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
        for var in ("PUBSUB_TOPIC", "GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT",
                    "MQTT_QOS", "MQTT_CONSUMER_CLIENTS", "DEVICE_IDENTIFIERS",
                    "EVENT_TYPE_TOPIC_MAP", "EVENT_TYPE_JSON_FIELDS"):
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

    def test_consumer_clients_partition(self, monkeypatch):
        self._base_env(monkeypatch)
        monkeypatch.delenv("MQTT_TOPIC")
        monkeypatch.setenv("DEVICE_IDENTIFIERS", "a,b,c")
        monkeypatch.setenv("MQTT_CONSUMER_CLIENTS", "2")
        s = main.Settings.from_env()
        assert len(s.mqtt_filter_groups) == 2
