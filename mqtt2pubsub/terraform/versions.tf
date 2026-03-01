terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Remote state in the shared GCS bucket managed by data-platform-gcp.
  # The bucket is created by bootstrap.sh; prefix isolates this app's state.
  backend "gcs" {
    bucket = "YOUR-PROJECT-ID-tfstate"
    prefix = "mqtt2pubsub"
  }
}
