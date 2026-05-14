variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "app_id" {
  description = "Application identifier used in jsonPayload.application filter (e.g. nivesh-main-app)"
  type        = string
}

variable "app_label" {
  description = "Human-readable application name for dashboard titles (e.g. Nivesh Main App)"
  type        = string
}

variable "notification_channel_ids" {
  description = "List of Cloud Monitoring notification channel IDs for alert policies"
  type        = list(string)
  default     = []
}

variable "features" {
  description = "Extra dashboard features to enable. Allowed: pipeline_analysis, audit_analysis, config_change_analysis"
  type        = set(string)
  default     = []
}

variable "alert_error_spike_threshold" {
  description = "5xx error count per 5-minute window that triggers the error-spike alert"
  type        = number
  default     = 10
}

variable "alert_latency_threshold_ms" {
  description = "P99 latency in ms that triggers the high-latency alert"
  type        = number
  default     = 5000
}

variable "alert_auth_failure_threshold" {
  description = "Auth failure count per 5-minute window that triggers the auth-failure alert"
  type        = number
  default     = 5
}
