output "operations_dashboard_id" {
  description = "Operations Overview dashboard resource ID"
  value       = google_monitoring_dashboard.operations.id
}

output "alert_policy_ids" {
  description = "Map of alert policy names to resource IDs"
  value = {
    error_spike  = google_monitoring_alert_policy.error_spike.id
    high_latency = google_monitoring_alert_policy.high_latency.id
    critical_log = google_monitoring_alert_policy.critical_log.id
    auth_failure = google_monitoring_alert_policy.auth_failure.id
    job_failure  = google_monitoring_alert_policy.job_failure.id
  }
}

output "log_metric_names" {
  description = "Map of log-based metric names created for this application"
  value = {
    request_count      = google_logging_metric.request_count.name
    error_4xx          = google_logging_metric.error_4xx_count.name
    error_5xx          = google_logging_metric.error_5xx_count.name
    exception_count    = google_logging_metric.exception_count.name
    request_latency    = google_logging_metric.request_latency.name
    auth_failure       = google_logging_metric.auth_failure_count.name
    critical_log       = google_logging_metric.critical_log_count.name
    job_failure        = google_logging_metric.job_failure_count.name
    job_run            = google_logging_metric.job_run_count.name
  }
}
