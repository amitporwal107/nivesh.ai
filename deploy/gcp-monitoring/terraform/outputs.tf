# ── Nivesh Main App ───────────────────────────────────────────────────────────
output "main_app_operations_dashboard_id" {
  description = "Nivesh Main App — Operations Overview dashboard ID"
  value       = module.nivesh_main_app.operations_dashboard_id
}

output "main_app_alert_policy_ids" {
  description = "Nivesh Main App — alert policy resource IDs"
  value       = module.nivesh_main_app.alert_policy_ids
}

# ── NIDP Console ──────────────────────────────────────────────────────────────
output "nidp_operations_dashboard_id" {
  description = "NIDP Console — Operations Overview dashboard ID"
  value       = module.nidp_console.operations_dashboard_id
}

output "nidp_alert_policy_ids" {
  description = "NIDP Console — alert policy resource IDs"
  value       = module.nidp_console.alert_policy_ids
}

# ── Admin App ─────────────────────────────────────────────────────────────────
output "admin_app_operations_dashboard_id" {
  description = "Admin App — Operations Overview dashboard ID"
  value       = module.admin_app.operations_dashboard_id
}

output "admin_app_alert_policy_ids" {
  description = "Admin App — alert policy resource IDs"
  value       = module.admin_app.alert_policy_ids
}
