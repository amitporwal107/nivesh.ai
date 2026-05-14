# ─────────────────────────────────────────────────────────────────────────────
# Nivesh GCP Monitoring — instantiates the app_monitoring module for each app
#
# Applications:
#   nivesh-main-app  — customer-facing investment platform (GCE / Docker Compose)
#   nidp-console     — internal data pipeline console (Cloud Run Jobs)
#   admin-app        — administration portal (same process as main-app, path-tagged)
# ─────────────────────────────────────────────────────────────────────────────

module "nivesh_main_app" {
  source = "./modules/app_monitoring"

  project_id               = var.project_id
  app_id                   = "nivesh-main-app"
  app_label                = "Nivesh Main App"
  notification_channel_ids = var.notification_channel_ids

  alert_error_spike_threshold  = var.main_app_error_spike_threshold
  alert_latency_threshold_ms   = var.main_app_latency_threshold_ms
  alert_auth_failure_threshold = var.main_app_auth_failure_threshold
}

module "nidp_console" {
  source = "./modules/app_monitoring"

  project_id               = var.project_id
  app_id                   = "nidp-console"
  app_label                = "NIDP Console"
  notification_channel_ids = var.notification_channel_ids

  features = ["pipeline_analysis"]

  alert_error_spike_threshold  = var.nidp_error_spike_threshold
  alert_latency_threshold_ms   = var.nidp_latency_threshold_ms
  alert_auth_failure_threshold = var.nidp_auth_failure_threshold
}

module "admin_app" {
  source = "./modules/app_monitoring"

  project_id               = var.project_id
  app_id                   = "admin-app"
  app_label                = "Admin App"
  notification_channel_ids = var.notification_channel_ids

  features = ["audit_analysis", "config_change_analysis"]

  alert_error_spike_threshold  = var.admin_error_spike_threshold
  alert_latency_threshold_ms   = var.admin_latency_threshold_ms
  alert_auth_failure_threshold = var.admin_auth_failure_threshold
}
