"""Tests for pants shipping workflow."""

from assetManagementFunctions import pantsShipping as ps


class DummyMessagebox:
    def showerror(self, title, message):
        return None


class DummyResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text


class DummyRequests:
    def __init__(self):
        self.post_payload = None
        self.put_payload = None

    def post(self, url, json=None, headers=None):
        self.post_payload = json
        return DummyResponse()

    def put(self, url, json=None, headers=None):
        self.put_payload = json
        return DummyResponse()


def test_pants_shipping_success(monkeypatch):
    dummy_requests = DummyRequests()

    monkeypatch.setattr(ps, "requests", dummy_requests)
    monkeypatch.setattr(
        ps,
        "getAssetInfo",
        lambda tag: ([], {"id": 10, "status_label": {"id": 5}, "model": {"id": 99}}),
    )
    monkeypatch.setattr(ps, "get_headers", lambda: {"Authorization": "token"})
    monkeypatch.setattr(ps, "get_settings", lambda: {"pantsShippingStatusId": "11"})
    monkeypatch.setattr(ps, "messagebox", DummyMessagebox())

    result = ps.pantsShipping("1234")

    assert result == "Pants shipping complete for 1234."
    assert dummy_requests.post_payload["status_id"] == 5
    assert dummy_requests.put_payload["status_id"] == 11
    assert dummy_requests.put_payload["model_id"] == 99


class DummyMessageboxTracker:
    def __init__(self):
        self.calls = []

    def showerror(self, title, message):
        self.calls.append((title, message))
        return None


class DummyRequestsPostFail(DummyRequests):
    def post(self, url, json=None, headers=None):
        self.post_payload = json
        return DummyResponse(status_code=500, text="boom")


class DummyRequestsPutFail(DummyRequests):
    def __init__(self):
        super().__init__()
        self._post_called = False

    def post(self, url, json=None, headers=None):
        self.post_payload = json
        self._post_called = True
        return DummyResponse(status_code=200)

    def put(self, url, json=None, headers=None):
        self.put_payload = json
        return DummyResponse(status_code=500, text="fail")


def test_pants_shipping_checkin_failure(monkeypatch):
    dummy_requests = DummyRequestsPostFail()
    dummy_msg = DummyMessageboxTracker()

    monkeypatch.setattr(ps, "requests", dummy_requests)
    monkeypatch.setattr(
        ps,
        "getAssetInfo",
        lambda tag: ([], {"id": 10, "status_label": {"id": 5}, "model": {"id": 99}}),
    )
    monkeypatch.setattr(ps, "get_headers", lambda: {"Authorization": "token"})
    monkeypatch.setattr(ps, "get_settings", lambda: {"pantsShippingStatusId": "11"})
    monkeypatch.setattr(ps, "messagebox", dummy_msg)

    result = ps.pantsShipping("1234")

    assert result == "Pants shipping failed for 1234: check-in failed."
    assert dummy_requests.put_payload is None
    assert dummy_msg.calls


def test_pants_shipping_update_failure(monkeypatch):
    dummy_requests = DummyRequestsPutFail()
    dummy_msg = DummyMessageboxTracker()

    monkeypatch.setattr(ps, "requests", dummy_requests)
    monkeypatch.setattr(
        ps,
        "getAssetInfo",
        lambda tag: ([], {"id": 10, "status_label": {"id": 5}, "model": {"id": 99}}),
    )
    monkeypatch.setattr(ps, "get_headers", lambda: {"Authorization": "token"})
    monkeypatch.setattr(ps, "get_settings", lambda: {"pantsShippingStatusId": "11"})
    monkeypatch.setattr(ps, "messagebox", dummy_msg)

    result = ps.pantsShipping("1234")

    assert result == "Pants shipping failed for 1234: update failed."
    assert dummy_requests.post_payload["status_id"] == 5
    assert dummy_requests.put_payload["status_id"] == 11
    assert dummy_msg.calls
