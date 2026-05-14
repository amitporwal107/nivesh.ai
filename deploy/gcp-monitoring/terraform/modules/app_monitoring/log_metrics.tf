# ─────────────────────────────────────────────────────────────────────────────
# Log-based metrics  —  one set per application
#
# Naming convention:  {app_id}/{metric_slug}
# All metrics filter on jsonPayload.application="{app_id}" so dashboards
# for each application are completely isolated.
# ─────────────────────────────────────────────────────────────────────────────

locals {
  app = var.app_id
}

# ── 1. Total request count ────────────────────────────────────────────────────
resource "google_logging_metric" "request_count" {
  name        = "${local.app}/request-count"
  description = "[${var.app_label}] Total HTTP requests"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    jsonPayload.eventType="REQUEST"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "API endpoint path"
    }
    labels {
      key         = "http_status"
      value_type  = "INT64"
      description = "HTTP response status code"
    }
  }

  label_extractors = {
    "endpoint"    = "EXTRACT(jsonPayload.endpoint)"
    "http_status" = "EXTRACT(jsonPayload.httpStatus)"
  }
}

# ── 2. 4xx client error count ─────────────────────────────────────────────────
resource "google_logging_metric" "error_4xx_count" {
  name        = "${local.app}/error-4xx-count"
  description = "[${var.app_label}] HTTP 4xx client errors"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    jsonPayload.eventType="REQUEST"
    jsonPayload.httpStatus>=400
    jsonPayload.httpStatus<500
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "API endpoint"
    }
    labels {
      key         = "http_status"
      value_type  = "INT64"
      description = "HTTP status code"
    }
  }

  label_extractors = {
    "endpoint"    = "EXTRACT(jsonPayload.endpoint)"
    "http_status" = "EXTRACT(jsonPayload.httpStatus)"
  }
}

# ── 3. 5xx server error count ─────────────────────────────────────────────────
resource "google_logging_metric" "error_5xx_count" {
  name        = "${local.app}/error-5xx-count"
  description = "[${var.app_label}] HTTP 5xx server errors"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    jsonPayload.eventType="REQUEST"
    jsonPayload.httpStatus>=500
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "API endpoint"
    }
  }

  label_extractors = {
    "endpoint" = "EXTRACT(jsonPayload.endpoint)"
  }
}

# ── 4. Unhandled exception count ──────────────────────────────────────────────
resource "google_logging_metric" "exception_count" {
  name        = "${local.app}/exception-count"
  description = "[${var.app_label}] Unhandled exceptions (records with exceptionClass)"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    jsonPayload.exceptionClass!=""
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "exception_class"
      value_type  = "STRING"
      description = "Exception class name"
    }
  }

  label_extractors = {
    "exception_class" = "EXTRACT(jsonPayload.exceptionClass)"
  }
}

# ── 5. Request latency (distribution) ─────────────────────────────────────────
resource "google_logging_metric" "request_latency" {
  name        = "${local.app}/request-latency"
  description = "[${var.app_label}] API response time distribution in milliseconds"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    jsonPayload.eventType="REQUEST"
    jsonPayload.responseTimeMs!=""
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "DISTRIBUTION"
    unit        = "ms"
    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "API endpoint"
    }
  }

  value_extractor = "EXTRACT(jsonPayload.responseTimeMs)"

  label_extractors = {
    "endpoint" = "EXTRACT(jsonPayload.endpoint)"
  }

  bucket_options {
    explicit_buckets {
      bounds = [0, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 30000]
    }
  }
}

# ── 6. Authentication failure count ───────────────────────────────────────────
resource "google_logging_metric" "auth_failure_count" {
  name        = "${local.app}/auth-failure-count"
  description = "[${var.app_label}] Authentication / authorisation failures"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    (jsonPayload.eventType="AUTH_FAILURE"
     OR (jsonPayload.httpStatus=401 AND jsonPayload.eventType="REQUEST")
     OR (jsonPayload.httpStatus=403 AND jsonPayload.eventType="REQUEST"))
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "endpoint"
      value_type  = "STRING"
      description = "API endpoint"
    }
  }

  label_extractors = {
    "endpoint" = "EXTRACT(jsonPayload.endpoint)"
  }
}

# ── 7. Critical log count ─────────────────────────────────────────────────────
resource "google_logging_metric" "critical_log_count" {
  name        = "${local.app}/critical-log-count"
  description = "[${var.app_label}] CRITICAL severity log entries"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    severity="CRITICAL"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# ── 8. Scheduled job failure count ────────────────────────────────────────────
resource "google_logging_metric" "job_failure_count" {
  name        = "${local.app}/job-failure-count"
  description = "[${var.app_label}] Scheduled job / pipeline failures"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    (jsonPayload.eventType="JOB_FAILURE"
     OR (severity="ERROR" AND jsonPayload.jobName!=""))
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "job_name"
      value_type  = "STRING"
      description = "Scheduled job name"
    }
  }

  label_extractors = {
    "job_name" = "EXTRACT(jsonPayload.jobName)"
  }
}

# ── 9. Scheduled job run count ────────────────────────────────────────────────
resource "google_logging_metric" "job_run_count" {
  name        = "${local.app}/job-run-count"
  description = "[${var.app_label}] Scheduled job / pipeline runs (start events)"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    (jsonPayload.eventType="JOB_RUN"
     OR jsonPayload.eventType="JOB_START")
    jsonPayload.jobName!=""
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "job_name"
      value_type  = "STRING"
      description = "Scheduled job name"
    }
  }

  label_extractors = {
    "job_name" = "EXTRACT(jsonPayload.jobName)"
  }
}

# ── 10. Admin / audit action count (admin-app only) ───────────────────────────
resource "google_logging_metric" "audit_action_count" {
  count       = contains(var.features, "audit_analysis") ? 1 : 0
  name        = "${local.app}/audit-action-count"
  description = "[${var.app_label}] Admin audit actions (login, config changes, user management)"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    (jsonPayload.eventType="AUDIT_ACTION"
     OR jsonPayload.eventType="CONFIG_CHANGE"
     OR jsonPayload.eventType="USER_MANAGEMENT")
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "event_type"
      value_type  = "STRING"
      description = "Audit event type"
    }
  }

  label_extractors = {
    "event_type" = "EXTRACT(jsonPayload.eventType)"
  }
}

# ── 11. Pipeline data event count (nidp-console only) ────────────────────────
resource "google_logging_metric" "pipeline_event_count" {
  count       = contains(var.features, "pipeline_analysis") ? 1 : 0
  name        = "${local.app}/pipeline-event-count"
  description = "[${var.app_label}] Data pipeline events (ingest, transform, validate)"
  project     = var.project_id

  filter = <<-EOT
    jsonPayload.application="${local.app}"
    (jsonPayload.eventType="PIPELINE_EVENT"
     OR jsonPayload.eventType="DATA_EVENT"
     OR jsonPayload.eventType="INGEST_EVENT")
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "job_name"
      value_type  = "STRING"
      description = "Pipeline job name"
    }
  }

  label_extractors = {
    "job_name" = "EXTRACT(jsonPayload.jobName)"
  }
}
