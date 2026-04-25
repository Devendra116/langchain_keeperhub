"""Shared fixtures for langchain_keeperhub tests."""

from __future__ import annotations

import pytest

from langchain_keeperhub.client import KeeperHubClient

TEST_API_KEY = "kh_test_key_for_unit_tests"
TEST_BASE_URL = "https://test.keeperhub.local"


@pytest.fixture
def client() -> KeeperHubClient:
    return KeeperHubClient(
        api_key=TEST_API_KEY,
        base_url=TEST_BASE_URL,
    )
