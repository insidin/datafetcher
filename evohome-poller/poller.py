#!/usr/bin/env python3
"""Cloud Run Job poller for Evohome that publishes location status to Pub/Sub."""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from google.cloud import pubsub_v1, storage

LOGGER = logging.getLogger("evohome_poller")

HOST = "https://tccna.resideo.com"
TOKEN_URL = f"{HOST}/Auth/OAuth/Token"
API_BASE = f"{HOST}/WebAPI/emea/api/v1"

_BASIC_ID = "4a231089-d2b6-41bd-a5eb-16a0a422b999:1a15cdb8-42de-407b-add0-059f92c530cb"
_BASIC_AUTH = base64.b64encode(_BASIC_ID.encode()).decode()

HEADERS_BASE = {
    "Accept": "application/json",
    "Cache-Control": "no-cache, no-store",
    "Pragma": "no-cache",
}


class EvohomeError(Exception):
    """Raised when Evohome API interactions fail."""


@dataclass
class TokenData:
    access_token: str
    refresh_token: str
    expires_at: datetime

    @classmethod
    def from_response(cls, payload: dict[str, Any]) -> TokenData:
        required = ("access_token", "refresh_token", "expires_in")
        missing = [key for key in required if key not in payload]
        if missing:
            raise EvohomeError(f"Token response missing keys: {missing}")
        expires_at = datetime.now(UTC) + timedelta(seconds=int(payload["expires_in"]))
        return cls(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_at=expires_at,
        )

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> TokenData:
        return cls(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
        }

    def is_valid(self, skew_seconds: int = 30) -> bool:
        return self.expires_at - timedelta(seconds=skew_seconds) > datetime.now(UTC)


class TokenManager:
    """Fetches and refreshes Evohome OAuth tokens."""

    def __init__(self, username: str, password: str, cache_path: Path | None) -> None:
        self.username = username
        self.password = password
        self.cache_path = cache_path
        self._token: TokenData | None = None
        if cache_path:
            self._load_cache()

    def _load_cache(self) -> None:
        assert self.cache_path is not None
        try:
            self._token = TokenData.from_json(json.loads(self.cache_path.read_text()))
        except FileNotFoundError:
            self._token = None
        except Exception:
            LOGGER.warning("Ignoring invalid token cache at %s", self.cache_path)
            self._token = None

    def _save_cache(self) -> None:
        if not self.cache_path or not self._token:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(self._token.to_json(), indent=2))

    def _auth_headers(self) -> dict[str, str]:
        return HEADERS_BASE | {"Authorization": f"Basic {_BASIC_AUTH}"}

    def _password_grant(self) -> TokenData:
        data = {
            "grant_type": "password",
            "scope": "EMEA-V1-Basic EMEA-V1-Anonymous",
            "Username": self.username,
            "Password": self.password,
        }
        response = requests.post(TOKEN_URL, headers=self._auth_headers(), data=data, timeout=30)
        response.raise_for_status()
        return TokenData.from_response(response.json())

    def _refresh_grant(self, refresh_token: str) -> TokenData:
        data = {
            "grant_type": "refresh_token",
            "scope": "EMEA-V1-Basic EMEA-V1-Anonymous",
            "refresh_token": refresh_token,
        }
        response = requests.post(TOKEN_URL, headers=self._auth_headers(), data=data, timeout=30)
        response.raise_for_status()
        return TokenData.from_response(response.json())

    def get_access_token(self) -> TokenData:
        if self._token and self._token.is_valid():
            return self._token

        if self._token and self._token.refresh_token:
            try:
                self._token = self._refresh_grant(self._token.refresh_token)
                self._save_cache()
                return self._token
            except requests.HTTPError as err:
                if err.response is None or err.response.status_code not in (400, 401):
                    raise

        self._token = self._password_grant()
        self._save_cache()
        return self._token

    def force_refresh(self) -> TokenData:
        if not self._token or not self._token.refresh_token:
            raise EvohomeError("No refresh token available")
        self._token = self._refresh_grant(self._token.refresh_token)
        self._save_cache()
        return self._token


def _request_with_auth(tm: TokenManager, method: str, url: str, **kwargs: Any) -> Any:
    headers = kwargs.pop("headers", {})

    def do_request(token: TokenData) -> requests.Response:
        merged_headers = HEADERS_BASE | headers | {"Authorization": f"bearer {token.access_token}"}
        return requests.request(method=method, url=url, headers=merged_headers, timeout=30, **kwargs)

    response = do_request(tm.get_access_token())
    if response.status_code == 401:
        tm.force_refresh()
        response = do_request(tm.get_access_token())

    response.raise_for_status()
    return response.json()


def fetch_location_status(tm: TokenManager, location_id: str) -> Any:
    url = f"{API_BASE}/location/{location_id}/status?includeTemperatureControlSystems=True"
    return _request_with_auth(tm, "GET", url)


def is_gcs_uri(path: str) -> bool:
    return path.startswith("gs://")


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    without_scheme = uri[len("gs://") :]
    bucket, _, blob = without_scheme.partition("/")
    if not bucket or not blob:
        raise ValueError(f"Invalid GCS URI: {uri}")
    return bucket, blob


def sync_cache_from_gcs(cache_uri: str, local_path: Path) -> None:
    bucket_name, blob_name = parse_gcs_uri(cache_uri)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    if blob.exists():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(local_path)
        LOGGER.info("Downloaded token cache from %s", cache_uri)


def sync_cache_to_gcs(cache_uri: str, local_path: Path) -> None:
    if not local_path.exists():
        return
    bucket_name, blob_name = parse_gcs_uri(cache_uri)
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_filename(local_path)
    LOGGER.info("Uploaded token cache to %s", cache_uri)


def required_value(cli_value: str | None, env_var: str) -> str:
    if cli_value:
        return cli_value
    env_value = os.getenv(env_var)
    if env_value:
        return env_value
    cli_flag = env_var.lower().replace("_", "-")
    raise ValueError(f"Missing required value: --{cli_flag} or {env_var}")


def normalize_topic(topic: str, publisher: pubsub_v1.PublisherClient) -> str:
    if topic.startswith("projects/"):
        return topic
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not project_id:
        raise ValueError(
            "Topic must be fully-qualified (projects/<id>/topics/<name>) or GOOGLE_CLOUD_PROJECT must be set"
        )
    return publisher.topic_path(project_id, topic)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll Evohome location status and publish snapshots to Pub/Sub")
    parser.add_argument("--username", "-u", help="Evohome username (email)")
    parser.add_argument("--password", "-p", help="Evohome password")
    parser.add_argument("--location-id", "-l", default="7952144", help="Location ID")
    parser.add_argument(
        "--cache",
        help=(
            "Optional token cache path. Supports local files and gs://bucket/path.json; omit for in-memory tokens only"
        ),
    )
    parser.add_argument(
        "--pubsub-topic",
        help="Pub/Sub topic (full path projects/<id>/topics/<name> preferred)",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (INFO, DEBUG, ...)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    username = required_value(args.username, "EVOHOME_USERNAME")
    password = required_value(args.password, "EVOHOME_PASSWORD")
    topic_raw = required_value(args.pubsub_topic, "PUBSUB_TOPIC")

    cache_uri = args.cache
    cache_path_local: Path | None = None
    if cache_uri:
        if is_gcs_uri(cache_uri):
            cache_path_local = Path("/tmp/token_cache.json")  # noqa: S108
            sync_cache_from_gcs(cache_uri, cache_path_local)
        else:
            cache_path_local = Path(cache_uri)

    token_manager = TokenManager(username, password, cache_path=cache_path_local)
    status = fetch_location_status(token_manager, str(args.location_id))

    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        "location_id": str(args.location_id),
        "status": status,
    }

    publisher = pubsub_v1.PublisherClient()
    topic = normalize_topic(topic_raw, publisher)
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    future = publisher.publish(
        topic,
        data,
        location_id=str(args.location_id),
        source="evohome-poller",
    )
    message_id = future.result(timeout=30)
    LOGGER.info("Published message_id=%s to topic=%s", message_id, topic)

    if cache_uri and is_gcs_uri(cache_uri) and cache_path_local:
        sync_cache_to_gcs(cache_uri, cache_path_local)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:  # noqa: BLE001
        logging.exception("Fatal error during poller run: %s", err)
        raise SystemExit(1)
