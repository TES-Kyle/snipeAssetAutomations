"""Pytest configuration and safety guards."""

import os
import sys
import requests
import pytest


class NetworkBlocked(RuntimeError):
    """Raised when a test attempts a network call."""


def _blocked(*_args, **_kwargs):
    """Block all outbound HTTP calls during tests."""
    raise NetworkBlocked("Network calls are blocked during tests")


_ORIG_REQUEST = requests.request
_ORIG_GET = requests.get
_ORIG_SESSION_REQUEST = requests.Session.request


def _allow_get_request(method, url, **kwargs):
    """Permit GET requests only; block everything else."""
    if str(method).upper() != "GET":
        raise NetworkBlocked(f"Non-GET HTTP method blocked in read-only tests: {method}")
    return _ORIG_REQUEST(method, url, **kwargs)


def _allow_get(url, **kwargs):
    """Permit requests.get during read-only tests."""
    return _ORIG_GET(url, **kwargs)


def _allow_session_request(self, method, url, **kwargs):
    """Permit Session.request GET calls only."""
    if str(method).upper() != "GET":
        raise NetworkBlocked(f"Non-GET HTTP method blocked in read-only tests: {method}")
    return _ORIG_SESSION_REQUEST(self, method, url, **kwargs)


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    """Prevent real HTTP requests in the test suite unless read-only is enabled."""
    allow_readonly = bool(request.node.get_closest_marker("readonly_network"))
    readonly_enabled = os.environ.get("READONLY_NETWORK", "").lower() in ("1", "true", "yes", "on")
    if allow_readonly and readonly_enabled:
        monkeypatch.setattr(requests, "request", _allow_get_request)
        monkeypatch.setattr(requests, "get", _allow_get)
        monkeypatch.setattr(requests, "post", _blocked)
        monkeypatch.setattr(requests, "put", _blocked)
        monkeypatch.setattr(requests, "patch", _blocked)
        monkeypatch.setattr(requests, "delete", _blocked)
        monkeypatch.setattr(requests.Session, "request", _allow_session_request)
        yield
        return

    monkeypatch.setattr(requests, "request", _blocked)
    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests, "put", _blocked)
    monkeypatch.setattr(requests, "patch", _blocked)
    monkeypatch.setattr(requests, "delete", _blocked)
    monkeypatch.setattr(requests.Session, "request", _blocked)
    yield


def pytest_sessionstart(session):
    """Ensure the repo root is on sys.path for local imports."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
