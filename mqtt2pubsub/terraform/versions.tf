terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Partial backend configuration — bucket and prefix are passed at init time
  # by the deploy workflow using the GCP_PROJECT_ID secret:
  #   terraform init -backend-config="bucket=${PROJECT_ID}-tfstate" \
  #                  -backend-config="prefix=mqtt2pubsub"
  backend "gcs" {}
}
