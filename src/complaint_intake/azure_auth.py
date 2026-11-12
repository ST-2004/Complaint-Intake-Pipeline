"""Entra ID credentials and the hints we print when sign-in goes wrong."""

from __future__ import annotations

from azure.identity import AzureCliCredential, ChainedTokenCredential, EnvironmentCredential

# Known failure signatures -> the fix a human should try. Keep these short.
AUTH_HINTS: dict[str, str] = {
    "AADSTS70043": (
        "Your Azure CLI token expired under a conditional-access policy. "
        "Run: az login --use-device-code"
    ),
    "AADSTS700082": "Your refresh token expired. Run: az login --use-device-code",
    "Please run 'az login'": "Azure CLI is not signed in. Run: az login --use-device-code",
    "PermissionDenied": (
        "Signed in, but the role is missing or still propagating. Role assignments can "
        "take 5-10 minutes after `terraform apply`; wait and retry. If it persists, "
        "check assign_roles=true or ask an admin to grant the role on the account."
    ),
    "401": (
        "Token rejected. Check AZURE_TOKEN_SCOPE in .env: try "
        "https://cognitiveservices.azure.com/.default or https://ai.azure.com/.default"
    ),
    "403": (
        "Forbidden. Role assignments can take 5-10 minutes to propagate after apply; "
        "wait and retry."
    ),
    "DeploymentNotFound": (
        "The model deployment does not exist. Check MODEL_DEPLOYMENT, or whether "
        "deploy_model was false."
    ),
}


def get_credential() -> ChainedTokenCredential:
    """Service-principal env vars first (CI / automation), then the Azure CLI login."""
    return ChainedTokenCredential(EnvironmentCredential(), AzureCliCredential())


def hint_for(error: BaseException | str) -> str | None:
    text = str(error)
    for needle, hint in AUTH_HINTS.items():
        if needle in text:
            return hint
    return None
