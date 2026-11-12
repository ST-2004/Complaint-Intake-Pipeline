terraform {
  required_version = ">= 1.6"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state on purpose (git-ignored). See docs/cost-and-limits.md for an
  # optional Azure Storage remote-backend example.
}

provider "azurerm" {
  features {
    cognitive_account {
      # Cognitive Services accounts are soft-deleted on destroy; purging frees
      # the name and the one-F0-per-subscription slot immediately.
      purge_soft_delete_on_destroy = true
    }
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
  # subscription_id is read from ARM_SUBSCRIPTION_ID (required by azurerm 4.x).
  # `python tasks.py infra-up` sets it from your `az login` context.
}
