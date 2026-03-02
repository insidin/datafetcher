#!/usr/bin/env python3
"""
stream-pubsub.py — stream messages from the mqtt-ingest Pub/Sub topic.

Creates a temporary subscription, prints incoming messages, and cleans up on exit.
Requires Application Default Credentials: gcloud auth application-default login

Usage:
    python scripts/stream-pubsub.py --project <PROJECT_ID>
    python scripts/stream-pubsub.py --project <PROJECT_ID> --topic mqtt-ingest
    python scripts/stream-pubsub.py --project <PROJECT_ID> --max-messages 10
"""

import argparse
import json
import signal
import sys
import uuid
from datetime import UTC, datetime

try:
    from google.cloud import pubsub_v1
except ImportError:
    print("Missing dependency. Run: pip install google-cloud-pubsub", file=sys.stderr)
    sys.exit(1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stream messages from a Pub/Sub topic.")
    p.add_argument("--project", required=True, help="GCP project ID")
    p.add_argument("--topic", default="mqtt-ingest", help="Pub/Sub topic name (default: mqtt-ingest)")
    p.add_argument("--max-messages", type=int, default=0,
                   help="Stop after N messages; 0 = stream indefinitely (default: 0)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    project = args.project
    topic_id = args.topic
    max_messages = args.max_messages

    subscriber = pubsub_v1.SubscriberClient()
    topic_path = f"projects/{project}/topics/{topic_id}"
    sub_id = f"stream-test-{uuid.uuid4().hex[:8]}"
    sub_path = f"projects/{project}/subscriptions/{sub_id}"

    print(f"Topic:        {topic_path}")
    print(f"Subscription: {sub_path} (temporary, deleted on exit)")
    print(f"Max messages: {'unlimited' if max_messages == 0 else max_messages}")
    print("-" * 60)

    subscriber.create_subscription(request={"name": sub_path, "topic": topic_path})
    count = 0

    def cleanup(sig=None, frame=None) -> None:
        print(f"\nCleaning up subscription '{sub_id}'...")
        try:
            subscriber.delete_subscription(request={"subscription": sub_path})
        except Exception as e:
            print(f"Warning: could not delete subscription: {e}", file=sys.stderr)
        subscriber.close()
        print(f"Done. {count} message(s) received.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    def callback(message: pubsub_v1.types.PubsubMessage) -> None:
        nonlocal count
        count += 1
        ts = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]

        # Decode payload
        try:
            payload = json.loads(message.data.decode("utf-8"))
            payload_str = json.dumps(payload, indent=2)
        except Exception:
            payload_str = repr(message.data)

        # Print message
        print(f"\n[{ts}] message #{count}  id={message.message_id}")
        if message.attributes:
            for k, v in sorted(message.attributes.items()):
                print(f"  {k}: {v}")
        print(f"  payload:\n{_indent(payload_str, '    ')}")

        message.ack()

        if max_messages and count >= max_messages:
            cleanup()

    future = subscriber.subscribe(sub_path, callback=callback)
    print("Waiting for messages... (Ctrl+C to stop)\n")
    try:
        future.result()
    except Exception as e:
        print(f"Streaming error: {e}", file=sys.stderr)
        cleanup()


def _indent(text: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in text.splitlines())


if __name__ == "__main__":
    main()
