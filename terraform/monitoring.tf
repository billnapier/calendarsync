# --- Monitoring & Observability ---

resource "google_project_service" "monitoring_api" {
  service            = "monitoring.googleapis.com"
  disable_on_destroy = false
}

# Notification channel for alerts
resource "google_monitoring_notification_channel" "email_alert" {
  display_name = "Email Alert Channel"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  depends_on = [google_project_service.monitoring_api]
}

# Alert Policy 1: UI Errors (Cloud Run 5xx responses, excluding background tasks)
resource "google_monitoring_alert_policy" "ui_errors" {
  display_name = "CalendarSync UI High 5xx Error Rate"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run 5xx Errors > 5 in 5 minutes"
    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"${var.service_name}\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\" AND resource.labels.configuration_name != \"SYNC_ONE\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5.0
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email_alert.name
  ]

  depends_on = [google_project_service.monitoring_api]
}

# Alert Policy 2: Cron Tasks Errors (Failed Cloud Tasks)
resource "google_monitoring_alert_policy" "cron_errors" {
  display_name = "CalendarSync Cron Task Failures"
  combiner     = "OR"

  conditions {
    display_name = "High failed sync tasks (> 5 in 5 minutes)"
    condition_threshold {
      filter          = "resource.type = \"cloud_tasks_queue\" AND resource.labels.queue_id = \"sync-queue\" AND metric.type = \"cloudtasks.googleapis.com/queue/task_attempt_count\" AND metric.labels.response_code != \"OK\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 5.0
      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email_alert.name
  ]

  depends_on = [google_project_service.monitoring_api]
}

# Alert Policy 3: Cron Not Running (Absence of metrics from Cloud Scheduler)
resource "google_monitoring_alert_policy" "cron_absence" {
  display_name = "CalendarSync Cron Job Down"
  combiner     = "OR"

  conditions {
    display_name = "No trigger from Cloud Scheduler in 2 hours"
    condition_absent {
      filter   = "resource.type = \"cloud_scheduler_job\" AND resource.labels.job_id = \"${google_cloud_scheduler_job.sync_all.name}\" AND metric.type = \"cloudscheduler.googleapis.com/job/attempt_execution_count\""
      duration = "7200s" # 2 hours
      aggregations {
        alignment_period     = "3600s" # Check hourly alignment
        cross_series_reducer = "REDUCE_SUM"
        per_series_aligner   = "ALIGN_COUNT"
      }
    }
  }

  notification_channels = [
    google_monitoring_notification_channel.email_alert.name
  ]

  depends_on = [google_project_service.monitoring_api]
}

# Dashboard
resource "google_monitoring_dashboard" "calendarsync_dashboard" {
  dashboard_json = <<EOF
{
  "displayName": "CalendarSync Observability",
  "gridLayout": {
    "columns": "2",
    "widgets": [
      {
        "title": "Cloud Run Requests (All vs 5xx)",
        "xyChart": {
          "dataSets": [
            {
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"2xx\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "crossSeriesReducer": "REDUCE_SUM",
                    "perSeriesAligner": "ALIGN_RATE"
                  }
                }
              },
              "plotType": "LINE"
            },
            {
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.labels.response_code_class=\"5xx\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "crossSeriesReducer": "REDUCE_SUM",
                    "perSeriesAligner": "ALIGN_RATE"
                  }
                }
              },
              "plotType": "LINE"
            }
          ]
        }
      },
      {
        "title": "Cloud Tasks Attempts (Success vs Failure)",
        "xyChart": {
          "dataSets": [
            {
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"cloudtasks.googleapis.com/queue/task_attempt_count\" AND resource.type=\"cloud_tasks_queue\" AND resource.labels.queue_id=\"sync-queue\" AND metric.labels.response_code=\"OK\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "crossSeriesReducer": "REDUCE_SUM",
                    "perSeriesAligner": "ALIGN_RATE"
                  }
                }
              },
              "plotType": "LINE"
            },
            {
              "timeSeriesQuery": {
                "timeSeriesFilter": {
                  "filter": "metric.type=\"cloudtasks.googleapis.com/queue/task_attempt_count\" AND resource.type=\"cloud_tasks_queue\" AND resource.labels.queue_id=\"sync-queue\" AND metric.labels.response_code!=\"OK\"",
                  "aggregation": {
                    "alignmentPeriod": "60s",
                    "crossSeriesReducer": "REDUCE_SUM",
                    "perSeriesAligner": "ALIGN_RATE"
                  }
                }
              },
              "plotType": "LINE"
            }
          ]
        }
      },
      {
        "title": "Sync Completed Structured Logs",
        "logsPanel": {
          "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND textPayload:\"SYNC_STATS:\""
        }
      },
      {
        "title": "Sync Failure Structured Logs",
        "logsPanel": {
          "filter": "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND textPayload:\"SYNC_ERROR:\""
        }
      }
    ]
  }
}
EOF
  depends_on     = [google_project_service.monitoring_api]
}
