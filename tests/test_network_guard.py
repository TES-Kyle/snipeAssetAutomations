"""Verify the network guard behavior."""

import requests
import pytest

from tests.conftest import NetworkBlocked


def test_network_guard_blocks_post():
    with pytest.raises(NetworkBlocked):
        requests.post("https://example.com")


def test_network_guard_blocks_get_by_default():
    with pytest.raises(NetworkBlocked):
        requests.get("https://example.com")
