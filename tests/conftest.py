from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from config import Settings
from core.context import AppContext, build_context


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=None, gemini_api_key=None)


@pytest.fixture()
def context(settings: Settings) -> AppContext:
    return build_context(settings.model_copy(deep=True))


@pytest.fixture()
def client(context: AppContext) -> Iterator[TestClient]:
    app = create_app(context=context)
    with TestClient(app) as test_client:
        yield test_client
