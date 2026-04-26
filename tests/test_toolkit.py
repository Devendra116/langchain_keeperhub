"""Tests for KeeperHubToolkit surface shape."""

from __future__ import annotations

from langchain_core.tools import BaseToolkit

from langchain_keeperhub.toolkit import KeeperHubToolkit


def test_toolkit_is_a_basetoolkit() -> None:
    toolkit = KeeperHubToolkit(api_key="kh_test")
    assert isinstance(toolkit, BaseToolkit)
