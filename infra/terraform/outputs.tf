output "resource_group" {
  value = azurerm_resource_group.rg.name
}

output "location" {
  value = azurerm_resource_group.rg.location
}

output "language_account_name" {
  value = azurerm_cognitive_account.language.name
}

output "language_endpoint" {
  value = azurerm_cognitive_account.language.endpoint
}

output "ai_account_name" {
  value = azurerm_cognitive_account.ai.name
}

output "ai_endpoint" {
  description = "Account endpoint as reported by Azure (cognitiveservices.azure.com host)."
  value       = azurerm_cognitive_account.ai.endpoint
}

output "openai_v1_endpoint" {
  description = "OpenAI-compatible v1 base URL for the model deployment."
  value       = "https://${azurerm_cognitive_account.ai.custom_subdomain_name}.openai.azure.com/openai/v1/"
}

output "model_deployment" {
  value = var.model_deployment_name
}
