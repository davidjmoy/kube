output "app_url" {
  description = "Container App URL (HTTPS)"
  value       = "https://${azurerm_container_app.chatbot.ingress[0].fqdn}"
}

output "app_name" {
  description = "Container App name (for deploy script)"
  value       = azurerm_container_app.chatbot.name
}

output "acr_login_server" {
  description = "ACR login server"
  value       = azurerm_container_registry.acr.login_server
}

output "openai_endpoint" {
  description = "Azure OpenAI endpoint"
  value       = azurerm_cognitive_account.openai.endpoint
}

output "managed_identity_principal_id" {
  description = "User-assigned managed identity principal ID"
  value       = azurerm_user_assigned_identity.chatbot.principal_id
}
