variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "niveshdataintelligence"
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "asia-south1"
}

variable "notification_channel_ids" {
  description = "Cloud Monitoring notification channel IDs (email, PagerDuty, etc.)"
  type        = list(string)
  default     = []
}

# Per-app alert threshold overrides. Defaults match the module defaults.
variable "main_app_error_spike_threshold" {
  type    = number
  default = 10
}

variable "main_app_latency_threshold_ms" {
  type    = number
  default = 5000
}

variable "main_app_auth_failure_threshold" {
  type    = number
  default = 5
}

variable "nidp_error_spike_threshold" {
  type    = number
  default = 5
}

variable "nidp_latency_threshold_ms" {
  type    = number
  default = 30000
}

variable "nidp_auth_failure_threshold" {
  type    = number
  default = 3
}

variable "admin_error_spike_threshold" {
  type    = number
  default = 5
}

variable "admin_latency_threshold_ms" {
  type    = number
  default = 3000
}

variable "admin_auth_failure_threshold" {
  type    = number
  default = 3
}
