"""Set required environment variables before any test module imports main."""

import os

os.environ.setdefault("PUBSUB_SUBSCRIPTION", "projects/test/subscriptions/test-sub")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
