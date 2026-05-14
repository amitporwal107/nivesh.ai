# ─────────────────────────────────────────────────────────────────────────────
# Dashboards  —  Operations overview + drill-downs per application
# ─────────────────────────────────────────────────────────────────────────────

# ── Operations Dashboard (8 widgets) ─────────────────────────────────────────
resource "google_monitoring_dashboard" "operations" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Operations Overview"
    mosaicLayout = {
      columns = 12
      tiles = [
        # Row 1: Scorecards
        {
          width  = 3
          height = 3
          widget = {
            title = "Request Rate (req/min)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "60s"
                    perSeriesAligner   = "ALIGN_RATE"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_LINE" }
            }
          }
        },
        {
          xPos   = 3
          width  = 3
          height = 3
          widget = {
            title = "5xx Error Rate (errors/min)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/error-5xx-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "60s"
                    perSeriesAligner   = "ALIGN_RATE"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_LINE" }
              thresholds = [{
                value       = 0.1
                color       = "RED"
                direction   = "ABOVE"
                label       = "Alert threshold"
              }]
            }
          }
        },
        {
          xPos   = 6
          width  = 3
          height = 3
          widget = {
            title = "P99 Latency (ms)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "300s"
                    perSeriesAligner   = "ALIGN_PERCENTILE_99"
                    crossSeriesReducer = "REDUCE_PERCENTILE_99"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_LINE" }
              thresholds = [{
                value       = 5000
                color       = "YELLOW"
                direction   = "ABOVE"
                label       = "5s threshold"
              }]
            }
          }
        },
        {
          xPos   = 9
          width  = 3
          height = 3
          widget = {
            title = "Auth Failures (5-min)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/auth-failure-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "300s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_LINE" }
            }
          }
        },
        # Row 2: Request volume line chart
        {
          yPos   = 3
          width  = 8
          height = 4
          widget = {
            title = "Request Volume by Status Class"
            xyChart = {
              dataSets = [
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-count\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_RATE"
                        crossSeriesReducer = "REDUCE_SUM"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "Requests/min"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/error-5xx-count\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_RATE"
                        crossSeriesReducer = "REDUCE_SUM"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "5xx Errors/min"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/error-4xx-count\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "60s"
                        perSeriesAligner   = "ALIGN_RATE"
                        crossSeriesReducer = "REDUCE_SUM"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "4xx Errors/min"
                }
              ]
              yAxis = { label = "req/min", scale = "LINEAR" }
              timeshiftDuration = "0s"
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        # Row 2: Error breakdown pie
        {
          xPos   = 8
          yPos   = 3
          width  = 4
          height = 4
          widget = {
            title = "Error Rate (5xx / Total)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilterRatio = {
                    numerator = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/error-5xx-count\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_SUM"
                        crossSeriesReducer = "REDUCE_SUM"
                      }
                    }
                    denominator = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-count\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_SUM"
                        crossSeriesReducer = "REDUCE_SUM"
                      }
                    }
                  }
                }
                plotType    = "LINE"
                legendTemplate = "Error Rate"
              }]
              yAxis = { label = "ratio", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        # Row 3: Latency heatmap / histogram
        {
          yPos   = 7
          width  = 8
          height = 4
          widget = {
            title = "API Latency Distribution (P50 / P95 / P99)"
            xyChart = {
              dataSets = [
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_50"
                        crossSeriesReducer = "REDUCE_PERCENTILE_50"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "P50 (ms)"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_95"
                        crossSeriesReducer = "REDUCE_PERCENTILE_95"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "P95 (ms)"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_99"
                        crossSeriesReducer = "REDUCE_PERCENTILE_99"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "P99 (ms)"
                }
              ]
              yAxis = { label = "ms", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        # Row 3: Job health scorecard
        {
          xPos   = 8
          yPos   = 7
          width  = 4
          height = 4
          widget = {
            title = "Scheduled Job Failures"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/job-failure-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "300s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.labels.job_name"]
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "$${metric.labels.job_name}"
              }]
              yAxis = { label = "failures", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [
    google_logging_metric.request_count,
    google_logging_metric.error_4xx_count,
    google_logging_metric.error_5xx_count,
    google_logging_metric.request_latency,
    google_logging_metric.auth_failure_count,
    google_logging_metric.job_failure_count,
  ]
}

# ── Error Analysis Dashboard ──────────────────────────────────────────────────
resource "google_monitoring_dashboard" "error_analysis" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Error Analysis"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 4
          widget = {
            title = "5xx Errors by Endpoint"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/error-5xx-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "300s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.labels.endpoint"]
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "$${metric.labels.endpoint}"
              }]
              yAxis = { label = "5xx errors", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 4
          widget = {
            title = "4xx Errors by Endpoint"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/error-4xx-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "300s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.labels.endpoint"]
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "$${metric.labels.endpoint}"
              }]
              yAxis = { label = "4xx errors", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        {
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Exception Distribution by Class"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/exception-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "300s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.labels.exception_class"]
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "$${metric.labels.exception_class}"
              }]
              yAxis = { label = "exceptions", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        {
          xPos   = 6
          yPos   = 4
          width  = 6
          height = 4
          widget = {
            title = "Critical Log Entries Over Time"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/critical-log-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "300s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "CRITICAL logs"
              }]
              yAxis = { label = "count", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [
    google_logging_metric.error_4xx_count,
    google_logging_metric.error_5xx_count,
    google_logging_metric.exception_count,
    google_logging_metric.critical_log_count,
  ]
}

# ── Latency Analysis Dashboard ────────────────────────────────────────────────
resource "google_monitoring_dashboard" "latency_analysis" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Latency Analysis"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 4
          height = 3
          widget = {
            title = "P50 Latency"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "300s"
                    perSeriesAligner   = "ALIGN_PERCENTILE_50"
                    crossSeriesReducer = "REDUCE_PERCENTILE_50"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_LINE" }
            }
          }
        },
        {
          xPos   = 4
          width  = 4
          height = 3
          widget = {
            title = "P95 Latency"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "300s"
                    perSeriesAligner   = "ALIGN_PERCENTILE_95"
                    crossSeriesReducer = "REDUCE_PERCENTILE_95"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_LINE" }
            }
          }
        },
        {
          xPos   = 8
          width  = 4
          height = 3
          widget = {
            title = "P99 Latency"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "300s"
                    perSeriesAligner   = "ALIGN_PERCENTILE_99"
                    crossSeriesReducer = "REDUCE_PERCENTILE_99"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_LINE" }
              thresholds = [{
                value     = 5000
                color     = "RED"
                direction = "ABOVE"
                label     = "Alert: 5s"
              }]
            }
          }
        },
        {
          yPos   = 3
          width  = 12
          height = 5
          widget = {
            title = "Latency Percentiles Over Time"
            xyChart = {
              dataSets = [
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_50"
                        crossSeriesReducer = "REDUCE_PERCENTILE_50"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "P50"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_95"
                        crossSeriesReducer = "REDUCE_PERCENTILE_95"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "P95"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "300s"
                        perSeriesAligner   = "ALIGN_PERCENTILE_99"
                        crossSeriesReducer = "REDUCE_PERCENTILE_99"
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "P99"
                }
              ]
              yAxis = { label = "ms", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        {
          yPos   = 8
          width  = 12
          height = 4
          widget = {
            title = "Slowest Endpoints (P95 Latency)"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/request-latency\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_PERCENTILE_95"
                      crossSeriesReducer = "REDUCE_PERCENTILE_95"
                      groupByFields      = ["metric.labels.endpoint"]
                    }
                    pickTimeSeriesFilter = {
                      rankingMethod = "METHOD_MEAN"
                      numTimeSeries = 10
                      direction     = "TOP"
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "$${metric.labels.endpoint}"
              }]
              yAxis = { label = "P95 ms", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [google_logging_metric.request_latency]
}

# ── Auth Analysis Dashboard ───────────────────────────────────────────────────
resource "google_monitoring_dashboard" "auth_analysis" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Auth & Security Analysis"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 4
          height = 3
          widget = {
            title = "Auth Failures (1h)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/auth-failure-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "3600s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_BAR" }
            }
          }
        },
        {
          xPos   = 4
          width  = 8
          height = 3
          widget = {
            title = "Auth Failures Over Time"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/auth-failure-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "300s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "Auth failures"
              }]
              yAxis = { label = "failures/5min", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        },
        {
          yPos   = 3
          width  = 12
          height = 4
          widget = {
            title = "Auth Failures by Endpoint"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/auth-failure-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.labels.endpoint"]
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "$${metric.labels.endpoint}"
              }]
              yAxis = { label = "failures/hr", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [google_logging_metric.auth_failure_count]
}

# ── Job Monitoring Dashboard ──────────────────────────────────────────────────
resource "google_monitoring_dashboard" "job_monitoring" {
  project        = var.project_id
  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Job & Pipeline Monitoring"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 3
          widget = {
            title = "Job Runs by Name (24h)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/job-run-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "86400s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_BAR" }
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 3
          widget = {
            title = "Job Failures (24h)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/job-failure-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "86400s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_BAR" }
              thresholds = [{
                value     = 0
                color     = "RED"
                direction = "ABOVE"
                label     = "Any failure"
              }]
            }
          }
        },
        {
          yPos   = 3
          width  = 12
          height = 4
          widget = {
            title = "Job Run vs Failure Rate Over Time"
            xyChart = {
              dataSets = [
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/job-run-count\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "3600s"
                        perSeriesAligner   = "ALIGN_SUM"
                        crossSeriesReducer = "REDUCE_SUM"
                        groupByFields      = ["metric.labels.job_name"]
                      }
                    }
                  }
                  plotType    = "LINE"
                  legendTemplate = "Runs: $${metric.labels.job_name}"
                },
                {
                  timeSeriesQuery = {
                    timeSeriesFilter = {
                      filter = "metric.type=\"logging.googleapis.com/user/${local.app}/job-failure-count\" resource.type=\"gce_instance\""
                      aggregation = {
                        alignmentPeriod    = "3600s"
                        perSeriesAligner   = "ALIGN_SUM"
                        crossSeriesReducer = "REDUCE_SUM"
                        groupByFields      = ["metric.labels.job_name"]
                      }
                    }
                  }
                  plotType    = "STACKED_BAR"
                  legendTemplate = "Failures: $${metric.labels.job_name}"
                }
              ]
              yAxis = { label = "count/hr", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [
    google_logging_metric.job_run_count,
    google_logging_metric.job_failure_count,
  ]
}

# ── NIDP Pipeline Analysis Dashboard (opt-in) ─────────────────────────────────
resource "google_monitoring_dashboard" "pipeline_analysis" {
  count   = contains(var.features, "pipeline_analysis") ? 1 : 0
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Pipeline Analysis"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 3
          widget = {
            title = "Pipeline Events by Job (1h)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/pipeline-event-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "3600s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_BAR" }
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 3
          widget = {
            title = "Job Failure Rate"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/job-failure-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "3600s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_BAR" }
            }
          }
        },
        {
          yPos   = 3
          width  = 12
          height = 5
          widget = {
            title = "Pipeline Events by Job Over Time"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/pipeline-event-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.labels.job_name"]
                    }
                  }
                }
                plotType    = "LINE"
                legendTemplate = "$${metric.labels.job_name}"
              }]
              yAxis = { label = "events/hr", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [
    google_logging_metric.pipeline_event_count,
    google_logging_metric.job_failure_count,
  ]
}

# ── Admin Audit Analysis Dashboard (opt-in) ───────────────────────────────────
resource "google_monitoring_dashboard" "audit_analysis" {
  count   = contains(var.features, "audit_analysis") ? 1 : 0
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Audit & Admin Actions"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 6
          height = 3
          widget = {
            title = "Audit Actions (24h)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/audit-action-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "86400s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_BAR" }
            }
          }
        },
        {
          xPos   = 6
          width  = 6
          height = 3
          widget = {
            title = "Auth Failures (24h)"
            scorecard = {
              timeSeriesQuery = {
                timeSeriesFilter = {
                  filter = "metric.type=\"logging.googleapis.com/user/${local.app}/auth-failure-count\" resource.type=\"gce_instance\""
                  aggregation = {
                    alignmentPeriod    = "86400s"
                    perSeriesAligner   = "ALIGN_SUM"
                    crossSeriesReducer = "REDUCE_SUM"
                  }
                }
              }
              sparkChartView = { sparkChartType = "SPARK_BAR" }
            }
          }
        },
        {
          yPos   = 3
          width  = 12
          height = 5
          widget = {
            title = "Admin Actions by Event Type"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/audit-action-count\" resource.type=\"gce_instance\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                      groupByFields      = ["metric.labels.event_type"]
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "$${metric.labels.event_type}"
              }]
              yAxis = { label = "actions/hr", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [
    google_logging_metric.audit_action_count,
    google_logging_metric.auth_failure_count,
  ]
}

# ── Config Change Analysis Dashboard (opt-in) ─────────────────────────────────
resource "google_monitoring_dashboard" "config_change_analysis" {
  count   = contains(var.features, "config_change_analysis") ? 1 : 0
  project = var.project_id

  dashboard_json = jsonencode({
    displayName = "${var.app_label} — Config Change Analysis"
    mosaicLayout = {
      columns = 12
      tiles = [
        {
          width  = 12
          height = 4
          widget = {
            title = "Config Change Events Over Time"
            xyChart = {
              dataSets = [{
                timeSeriesQuery = {
                  timeSeriesFilter = {
                    filter = "metric.type=\"logging.googleapis.com/user/${local.app}/audit-action-count\" resource.type=\"gce_instance\" metric.label.event_type=\"CONFIG_CHANGE\""
                    aggregation = {
                      alignmentPeriod    = "3600s"
                      perSeriesAligner   = "ALIGN_SUM"
                      crossSeriesReducer = "REDUCE_SUM"
                    }
                  }
                }
                plotType    = "STACKED_BAR"
                legendTemplate = "Config changes/hr"
              }]
              yAxis = { label = "changes/hr", scale = "LINEAR" }
              chartOptions = { mode = "COLOR" }
            }
          }
        }
      ]
    }
  })

  depends_on = [google_logging_metric.audit_action_count]
}
