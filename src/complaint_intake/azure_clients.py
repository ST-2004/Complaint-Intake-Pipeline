"""Factories for Azure SDK clients, configured with Entra ID auth and timeouts."""

from __future__ import annotations

from complaint_intake.azure_auth import get_credential
from complaint_intake.config import Settings


class ConfigError(RuntimeError):
    """A required setting is missing."""


def make_language_client(settings: Settings, credential=None):
    from azure.ai.textanalytics import TextAnalyticsClient

    if not settings.azure_language_endpoint:
        raise ConfigError("AZURE_LANGUAGE_ENDPOINT is not set; run `python tasks.py env`")
    return TextAnalyticsClient(
        endpoint=settings.azure_language_endpoint,
        credential=credential or get_credential(),
        retry_total=2,
        connection_timeout=10,
        read_timeout=settings.request_timeout_s,
    )
