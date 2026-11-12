variable "project" {
  description = "Short project name used in resource names (lowercase letters and digits)."
  type        = string
  default     = "complaints"

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,15}$", var.project))
    error_message = "project must be 2-16 lowercase letters/digits, starting with a letter."
  }
}

variable "environment" {
  description = "Environment label used in resource names."
  type        = string
  default     = "dev"

  validation {
    condition     = can(regex("^[a-z0-9]{1,8}$", var.environment))
    error_message = "environment must be 1-8 lowercase letters/digits."
  }
}

variable "location" {
  description = "Azure region. Region policy differs per subscription: run scripts/preflight.py first."
  type        = string
  default     = "eastus2"
}

variable "language_sku" {
  description = "Azure AI Language SKU. F0 is free but limited to one per subscription; use S if F0 is taken."
  type        = string
  default     = "F0"

  validation {
    condition     = contains(["F0", "S"], var.language_sku)
    error_message = "language_sku must be F0 or S."
  }
}

variable "deploy_model" {
  description = "Create the model deployment. Set false to skip it (for example, no quota) and point MODEL_DEPLOYMENT at an existing one."
  type        = bool
  default     = true
}

variable "model_deployment_name" {
  description = "Name of the model deployment (what the client passes as `model`)."
  type        = string
  default     = "triage-model"
}

variable "model_name" {
  description = "Model to deploy."
  type        = string
  default     = "gpt-4.1-mini"
}

variable "model_version" {
  description = "Model version. Must exist in the chosen region (az cognitiveservices model list -l <region>)."
  type        = string
  default     = "2025-04-14"
}

variable "model_sku" {
  description = "Deployment type, e.g. GlobalStandard, Standard, DataZoneStandard. Depends on quota."
  type        = string
  default     = "GlobalStandard"
}

variable "model_capacity" {
  description = "Deployment capacity in thousands of tokens per minute."
  type        = number
  default     = 10

  validation {
    condition     = var.model_capacity >= 1
    error_message = "model_capacity must be at least 1."
  }
}

variable "assign_roles" {
  description = "Create Entra ID role assignments for the signed-in identity. Set false if you lack rights to create role assignments."
  type        = bool
  default     = true
}

variable "local_auth_enabled" {
  description = "Allow key-based auth on the accounts. Keep false (Entra ID only); enable only as a documented local-testing fallback."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Extra tags merged onto every resource."
  type        = map(string)
  default     = {}
}
