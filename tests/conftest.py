from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from config import Settings
from tools.context import AppContext, build_context


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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
