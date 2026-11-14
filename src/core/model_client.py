"""The one place a model client is constructed.

The API key is passed explicitly rather than left to the provider's own
environment lookup, so the key only ever has to exist in the validated settings
and a key living solely in `.env` still works.

The call goes through the shared HTTP client from `tools.retry_transport`, so a
transient provider failure is absorbed there rather than ending the run.
"""

from functools import lru_cache

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config.settings import settings
from tools.retry_transport import build_model_http_client


@lru_cache(maxsize=1)
def build_model() -> GoogleModel:
    """Return the shared chat model, built from validated settings.

    Cached, so every agent holds the same instance and the process opens one
    connection pool rather than one per agent.
    """
    return GoogleModel(
        settings.gemini_model,
        provider=GoogleProvider(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_client=build_model_http_client(),
        ),
    )
