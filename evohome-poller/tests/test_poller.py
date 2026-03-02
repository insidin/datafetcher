"""Unit tests for poller.py — no network or GCP credentials required."""

import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest

# poller.py lives one directory above this file
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import poller  # noqa: E402, I001


# ---------------------------------------------------------------------------
# is_gcs_uri
# ---------------------------------------------------------------------------


class TestIsGcsUri:
    def test_gcs_uri(self):
        assert poller.is_gcs_uri("gs://bucket/path")

    def test_local_path(self):
        assert not poller.is_gcs_uri("/tmp/local.json")  # noqa: S108

    def test_http_uri(self):
        assert not poller.is_gcs_uri("https://example.com/file")

    def test_empty_string(self):
        assert not poller.is_gcs_uri("")

    def test_gs_prefix_only(self):
        assert poller.is_gcs_uri("gs://bucket/nested/path/token.json")


# ---------------------------------------------------------------------------
# parse_gcs_uri
# ---------------------------------------------------------------------------


class TestParseGcsUri:
    def test_simple_path(self):
        bucket, blob = poller.parse_gcs_uri("gs://my-bucket/my-file.json")
        assert bucket == "my-bucket"
        assert blob == "my-file.json"

    def test_nested_path(self):
        bucket, blob = poller.parse_gcs_uri("gs://my-bucket/path/to/file.json")
        assert bucket == "my-bucket"
        assert blob == "path/to/file.json"

    def test_missing_blob_raises(self):
        with pytest.raises(ValueError, match="Invalid GCS URI"):
            poller.parse_gcs_uri("gs://bucket-only")

    def test_empty_bucket_raises(self):
        with pytest.raises(ValueError, match="Invalid GCS URI"):
            poller.parse_gcs_uri("gs:///just-blob.json")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid GCS URI"):
            poller.parse_gcs_uri("gs://")


# ---------------------------------------------------------------------------
# TokenData
# ---------------------------------------------------------------------------


class TestTokenData:
    def _valid_api_response(self, expires_in: int = 3600) -> dict:
        return {
            "access_token": "access-token-123",
            "refresh_token": "refresh-token-456",
            "expires_in": expires_in,
        }

    def test_from_response_access_token(self):
        td = poller.TokenData.from_response(self._valid_api_response())
        assert td.access_token == "access-token-123"

    def test_from_response_refresh_token(self):
        td = poller.TokenData.from_response(self._valid_api_response())
        assert td.refresh_token == "refresh-token-456"

    def test_from_response_expiry_is_roughly_now_plus_ttl(self):
        td = poller.TokenData.from_response(self._valid_api_response(expires_in=3600))
        delta = td.expires_at - datetime.now(UTC)
        assert 3590 <= delta.total_seconds() <= 3610

    def test_from_response_missing_key_raises(self):
        with pytest.raises(poller.EvohomeError, match="missing keys"):
            poller.TokenData.from_response({"access_token": "x"})

    def test_from_response_empty_dict_raises(self):
        with pytest.raises(poller.EvohomeError, match="missing keys"):
            poller.TokenData.from_response({})

    def test_round_trip_via_json(self):
        original = poller.TokenData.from_response(self._valid_api_response())
        serialised = original.to_json()
        restored = poller.TokenData.from_json(serialised)
        assert restored.access_token == original.access_token
        assert restored.refresh_token == original.refresh_token
        assert abs((restored.expires_at - original.expires_at).total_seconds()) < 1

    def test_to_json_contains_expected_keys(self):
        td = poller.TokenData.from_response(self._valid_api_response())
        data = td.to_json()
        assert set(data.keys()) == {"access_token", "refresh_token", "expires_at"}

    def test_is_valid_future_expiry(self):
        td = poller.TokenData.from_response(self._valid_api_response(expires_in=3600))
        assert td.is_valid()

    def test_is_invalid_already_expired(self):
        td = poller.TokenData(
            access_token="x",
            refresh_token="y",
            expires_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        assert not td.is_valid()

    def test_is_invalid_within_default_skew(self):
        # Token expires in 10s — within the default 30s skew, so treated as expired.
        td = poller.TokenData(
            access_token="x",
            refresh_token="y",
            expires_at=datetime.now(UTC) + timedelta(seconds=10),
        )
        assert not td.is_valid(skew_seconds=30)

    def test_is_valid_with_tight_skew(self):
        td = poller.TokenData(
            access_token="x",
            refresh_token="y",
            expires_at=datetime.now(UTC) + timedelta(seconds=20),
        )
        assert td.is_valid(skew_seconds=5)


# ---------------------------------------------------------------------------
# required_value
# ---------------------------------------------------------------------------


class TestRequiredValue:
    def test_cli_value_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "from-env")
        assert poller.required_value("from-cli", "MY_VAR") == "from-cli"

    def test_env_var_fallback_when_no_cli(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "from-env")
        assert poller.required_value(None, "MY_VAR") == "from-env"

    def test_missing_both_raises(self, monkeypatch):
        monkeypatch.delenv("MY_VAR", raising=False)
        with pytest.raises(ValueError, match="my-var"):
            poller.required_value(None, "MY_VAR")

    def test_empty_cli_value_falls_back_to_env(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "from-env")
        # Empty string is falsy — falls back to env var.
        assert poller.required_value("", "MY_VAR") == "from-env"

    def test_error_message_includes_env_var_as_flag(self, monkeypatch):
        monkeypatch.delenv("EVOHOME_USERNAME", raising=False)
        with pytest.raises(ValueError, match="evohome-username"):
            poller.required_value(None, "EVOHOME_USERNAME")


# ---------------------------------------------------------------------------
# TokenManager — cache load / save (no network, no GCS)
# ---------------------------------------------------------------------------


class TestTokenManagerLocalCache:
    def _write_token(self, path, expires_offset_sec: int = 3600) -> poller.TokenData:
        td = poller.TokenData(
            access_token="cached-access",
            refresh_token="cached-refresh",
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_offset_sec),
        )
        path.write_text(json.dumps(td.to_json()))
        return td

    def test_no_cache_file_token_is_none(self, tmp_path):
        cache_file = tmp_path / "missing.json"
        tm = poller.TokenManager("u", "p", cache_path=cache_file)
        assert tm._token is None

    def test_valid_cache_file_loaded_on_init(self, tmp_path):
        cache_file = tmp_path / "token.json"
        self._write_token(cache_file)
        tm = poller.TokenManager("u", "p", cache_path=cache_file)
        assert tm._token is not None
        assert tm._token.access_token == "cached-access"

    def test_invalid_json_cache_ignored(self, tmp_path):
        cache_file = tmp_path / "token.json"
        cache_file.write_text("not-valid-json{{{")
        tm = poller.TokenManager("u", "p", cache_path=cache_file)
        assert tm._token is None

    def test_no_cache_path_no_token(self):
        tm = poller.TokenManager("u", "p", cache_path=None)
        assert tm._token is None

    def test_save_cache_creates_file(self, tmp_path):
        cache_file = tmp_path / "subdir" / "token.json"
        tm = poller.TokenManager("u", "p", cache_path=cache_file)
        tm._token = poller.TokenData(
            access_token="saved-access",
            refresh_token="saved-refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        tm._save_cache()
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["access_token"] == "saved-access"

    def test_save_cache_no_path_is_noop(self):
        tm = poller.TokenManager("u", "p", cache_path=None)
        tm._token = poller.TokenData(
            access_token="x",
            refresh_token="y",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        tm._save_cache()  # should not raise

    def test_get_access_token_returns_cached_valid_token(self, tmp_path):
        cache_file = tmp_path / "token.json"
        self._write_token(cache_file, expires_offset_sec=3600)
        tm = poller.TokenManager("u", "p", cache_path=cache_file)
        result = tm.get_access_token()
        assert result.access_token == "cached-access"
