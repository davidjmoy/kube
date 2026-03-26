output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.aks.name
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "openai_endpoint" {
  value = azurerm_cognitive_account.openai.endpoint
}

output "public_ip" {
  value = azurerm_public_ip.chatbot.ip_address
}

output "managed_identity_client_id" {
  value = azurerm_user_assigned_identity.chatbot.client_id
}

output "aks_oidc_issuer" {
  value = azurerm_kubernetes_cluster.aks.oidc_issuer_url
}
