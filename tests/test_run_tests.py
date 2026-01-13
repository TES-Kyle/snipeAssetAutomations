"""Tests for pytest runner helper."""

from otherManagementFunctions import runTests


class DummyProc:
    def __init__(self, args, code=0):
        self.args = args
        self._code = code
        self.stdout = iter(["line1\n", "line2\n"])

    def wait(self):
        return self._code


def test_run_pytest_tests_default_verbosity(monkeypatch):
    captured = {}

    def fake_popen(args, **_kwargs):
        captured["args"] = args
        return DummyProc(args, code=0)

    monkeypatch.setattr(runTests, "get_settings", lambda: {"pytestVerbosity": "0"})
    monkeypatch.setattr(runTests.subprocess, "Popen", fake_popen)

    result = runTests.run_pytest_tests()

    assert "pytest" in captured["args"]
    assert "-v" not in captured["args"]
    assert result == "Pytest completed successfully."


def test_run_pytest_tests_verbose(monkeypatch):
    captured = {}

    def fake_popen(args, **_kwargs):
        captured["args"] = args
        return DummyProc(args, code=1)

    monkeypatch.setattr(runTests, "get_settings", lambda: {"pytestVerbosity": "2"})
    monkeypatch.setattr(runTests.subprocess, "Popen", fake_popen)

    result = runTests.run_pytest_tests()

    assert "-vv" in captured["args"]
    assert result == "Pytest finished with exit code 1."


def test_run_pytest_tests_extra_args_and_env(monkeypatch):
    captured = {}
    captured_env = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured_env.update(kwargs.get("env", {}))
        return DummyProc(args, code=0)

    monkeypatch.setattr(
        runTests,
        "get_settings",
        lambda: {
            "pytestVerbosity": "1",
            "pytestQuiet": "1",
            "pytestCapture": "1",
            "pytestFailFast": "1",
            "pytestMaxFail": "2",
            "pytestDurations": "3",
            "pytestMarkerExpression": "readonly_network",
            "pytestKeywordExpression": "api_user",
            "pytestAdditionalArgs": "--lf",
            "pytestTargets": "tests/test_api_user.py",
            "pytestReadonlyNetwork": "1",
            "pytestReadonlyAssetTags": "6057,6529",
            "pytestReadonlyApiUser": "Automation User",
            "pytestReadonlyApiKey": "token-123",
        },
    )
    monkeypatch.setattr(runTests.subprocess, "Popen", fake_popen)

    result = runTests.run_pytest_tests()

    assert "-v" in captured["args"]
    assert "-q" in captured["args"]
    assert "-s" in captured["args"]
    assert "-x" in captured["args"]
    assert "--maxfail=2" in captured["args"]
    assert "--durations=3" in captured["args"]
    def _last_arg_value(flag):
        indices = [i for i, item in enumerate(captured["args"]) if item == flag]
        assert indices
        return captured["args"][indices[-1] + 1]

    assert _last_arg_value("-m") == "readonly_network"
    assert _last_arg_value("-k") == "api_user"
    assert "--lf" in captured["args"]
    assert "tests/test_api_user.py" in captured["args"]
    assert captured_env.get("READONLY_NETWORK") == "1"
    assert captured_env.get("READONLY_ASSET_TAGS") == "6057,6529"
    assert captured_env.get("READONLY_API_USER") == "Automation User"
    assert captured_env.get("READONLY_API_KEY") == "token-123"
    assert result == "Pytest completed successfully."
