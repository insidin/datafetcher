#!/usr/bin/env python3
"""Publish one MQTT message for local testing."""

from __future__ import annotations

import argparse

import paho.mqtt.client as mqtt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish a test MQTT message")
    parser.add_argument("--host", default="127.0.0.1", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--topic", default="devices/test/telemetry", help="MQTT topic")
    parser.add_argument("--message", default='{"hello":"world"}', help="Payload text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="mqtt2pubsub-local-publisher",
    )
    client.connect(args.host, args.port, 60)
    info = client.publish(args.topic, payload=args.message.encode("utf-8"), qos=1, retain=False)
    info.wait_for_publish()
    client.disconnect()
    print(f"published topic={args.topic} qos=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
