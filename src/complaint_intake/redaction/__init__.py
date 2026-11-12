"""PII redaction: one interface, two providers (Azure AI Language, Presidio)."""

from __future__ import annotations

from complaint_intake.config import PiiProvider, Settings
from complaint_intake.redaction.base import RedactionError, RedactionResult, Redactor

__all__ = ["RedactionError", "RedactionResult", "Redactor", "get_redactor"]


def get_redactor(settings: Settings, *, credential=None) -> Redactor:
    """Build the redactor selected by PII_PROVIDER."""
    if settings.pii_provider is PiiProvider.PRESIDIO:
        from complaint_intake.redaction.presidio import PresidioRedactor

        return PresidioRedactor(model=settings.presidio_model)

    from complaint_intake.azure_clients import make_language_client
    from complaint_intake.redaction.azure_language import AzureLanguageRedactor

    return AzureLanguageRedactor(make_language_client(settings, credential))
