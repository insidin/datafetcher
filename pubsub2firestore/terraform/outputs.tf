output "service_url" {
  description = "Cloud Run service URL."
  value       = google_cloud_run_v2_service.pubsub2firestore.uri
}

output "subscription_name" {
  description = "Pub/Sub subscription name."
  value       = google_pubsub_subscription.pubsub2firestore.name
}
