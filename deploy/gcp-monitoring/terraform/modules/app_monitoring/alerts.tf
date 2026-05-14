# ─────────────────────────────────────────────────────────────────────────────
# Alert Policies  —  one set per application
#
# All alerts reference the log-based metrics created in log_metrics.tf.
# Thresholds are configurable via module variables.
# ─────────────────────────────────────────────────────────────────────────────

# ── 1. Error spike (5xx) ──────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "error_spike" {
  project      = var.project_id
  display_name = "[${var.app_label}] Error Spike — 5xx"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "5xx errors exceed threshold in 5-minute window"

    condition_threshold {
      filter = <<-EOT
        metric.type="logging.googleapis.com/user/${local.app}/error-5xx-count"
        resource.type="global"
      EOT

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_error_spike_threshold
      duration        = "0s"
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = "604800s"
  }

  documentation {
    content = <<-EOT
      **[${var.app_label}] 5xx Error Spike**

      The application is returning more than ${var.alert_error_spike_threshold} server errors
      in a 5-minute window. Investigate immediately.

      **Log query:**
      ```
      jsonPayload.application="${local.app}"
      jsonPayload.eventType="REQUEST"
      jsonPayload.httpStatus>=500
      ```
    EOT
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.error_5xx_count]
}

# ── 2. High latency (P99) ─────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "high_latency" {
  project      = var.project_id
  display_name = "[${var.app_label}] High API Latency — P99"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "P99 latency exceeds threshold"

    condition_threshold {
      filter = <<-EOT
        metric.type="logging.googleapis.com/user/${local.app}/request-latency"
        resource.type="global"
      EOT

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_PERCENTILE_99"
        cross_series_reducer = "REDUCE_PERCENTILE_99"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_latency_threshold_ms
      duration        = "60s"
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = "604800s"
  }

  documentation {
    content = <<-EOT
      **[${var.app_label}] High Latency Alert**

      P99 API latency has exceeded ${var.alert_latency_threshold_ms}ms.
      Check for slow database queries, downstream timeouts, or resource saturation.

      **Log query:**
      ```
      jsonPayload.application="${local.app}"
      jsonPayload.eventType="REQUEST"
      jsonPayload.responseTimeMs>5000
      ```
    EOT
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.request_latency]
}

# ── 3. Critical log ───────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "critical_log" {
  project      = var.project_id
  display_name = "[${var.app_label}] Critical Log Entry"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Any CRITICAL severity log entry"

    condition_threshold {
      filter = <<-EOT
        metric.type="logging.googleapis.com/user/${local.app}/critical-log-count"
        resource.type="global"
      EOT

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = "604800s"
  }

  documentation {
    content = <<-EOT
      **[${var.app_label}] CRITICAL Log Detected**

      A CRITICAL severity log entry was emitted. This indicates a fatal
      startup failure or system-level error requiring immediate investigation.

      **Log query:**
      ```
      jsonPayload.application="${local.app}"
      severity="CRITICAL"
      ```
    EOT
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.critical_log_count]
}

# ── 4. Authentication failure spike ───────────────────────────────────────────
resource "google_monitoring_alert_policy" "auth_failure" {
  project      = var.project_id
  display_name = "[${var.app_label}] Auth Failure Spike"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Auth failures exceed threshold in 5-minute window"

    condition_threshold {
      filter = <<-EOT
        metric.type="logging.googleapis.com/user/${local.app}/auth-failure-count"
        resource.type="global"
      EOT

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = var.alert_auth_failure_threshold
      duration        = "0s"
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = "604800s"
  }

  documentation {
    content = <<-EOT
      **[${var.app_label}] Authentication Failure Spike**

      More than ${var.alert_auth_failure_threshold} authentication failures in a 5-minute window.
      Possible brute-force attack or misconfigured client credentials.

      **Log query:**
      ```
      jsonPayload.application="${local.app}"
      (jsonPayload.httpStatus=401 OR jsonPayload.httpStatus=403)
      jsonPayload.eventType="REQUEST"
      ```
    EOT
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.auth_failure_count]
}

# ── 5. Job failure ────────────────────────────────────────────────────────────
resource "google_monitoring_alert_policy" "job_failure" {
  project      = var.project_id
  display_name = "[${var.app_label}] Scheduled Job Failure"
  combiner     = "OR"
  enabled      = true

  conditions {
    display_name = "Any scheduled job failure"

    condition_threshold {
      filter = <<-EOT
        metric.type="logging.googleapis.com/user/${local.app}/job-failure-count"
        resource.type="global"
      EOT

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"
    }
  }

  notification_channels = var.notification_channel_ids

  alert_strategy {
    auto_close = "604800s"
  }

  documentation {
    content = <<-EOT
      **[${var.app_label}] Scheduled Job Failure**

      A scheduled job or pipeline has reported a failure. Check the jobName
      label in the alert for the specific job, and investigate log entries.

      **Log query:**
      ```
      jsonPayload.application="${local.app}"
      jsonPayload.eventType="JOB_FAILURE"
      ```
    EOT
    mime_type = "text/markdown"
  }

  depends_on = [google_logging_metric.job_failure_count]
}
