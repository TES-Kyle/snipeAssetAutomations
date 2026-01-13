"""Run the pytest suite from within the GUI."""

import logging
import os
import shlex
import subprocess
import sys

from utilities.logging_utils import configure_logging, get_settings

logger = logging.getLogger(__name__)


def run_pytest_tests():
    """Execute pytest and stream output to the script log window.

    Returns:
        Status message string for the main UI.
    """
    configure_logging()
    settings = get_settings()

    def _to_bool(value):
        raw = str(value if value is not None else "").strip().lower()
        return raw in ("1", "true", "yes", "on")

    def _to_int(value, default=0):
        try:
            return int(str(value).strip())
        except Exception:
            return default

    verbosity = _to_int(settings.get("pytestVerbosity", 0), 0)
    quiet = _to_bool(settings.get("pytestQuiet", "0"))
    capture = _to_bool(settings.get("pytestCapture", "0"))
    fail_fast = _to_bool(settings.get("pytestFailFast", "0"))
    max_fail = _to_int(settings.get("pytestMaxFail", 0), 0)
    durations = _to_int(settings.get("pytestDurations", 0), 0)
    marker_expr = str(settings.get("pytestMarkerExpression", "")).strip()
    keyword_expr = str(settings.get("pytestKeywordExpression", "")).strip()
    extra_args = str(settings.get("pytestAdditionalArgs", "")).strip()
    targets = str(settings.get("pytestTargets", "")).strip()

    args = [sys.executable, "-m", "pytest"]
    if verbosity >= 2:
        args.append("-vv")
    elif verbosity == 1:
        args.append("-v")
    if quiet:
        args.append("-q")
    if capture:
        args.append("-s")
    if fail_fast:
        args.append("-x")
    if max_fail > 0:
        args.append(f"--maxfail={max_fail}")
    if durations > 0:
        args.append(f"--durations={durations}")
    if marker_expr:
        args.extend(["-m", marker_expr])
    if keyword_expr:
        args.extend(["-k", keyword_expr])
    if extra_args:
        args.extend(shlex.split(extra_args))
    if targets:
        args.extend(shlex.split(targets))

    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if _to_bool(settings.get("pytestReadonlyNetwork", "0")):
        env["READONLY_NETWORK"] = "1"
    readonly_tags = str(settings.get("pytestReadonlyAssetTags", "")).strip()
    if readonly_tags:
        env["READONLY_ASSET_TAGS"] = readonly_tags
    readonly_api_user = str(settings.get("pytestReadonlyApiUser", "")).strip()
    if readonly_api_user:
        env["READONLY_API_USER"] = readonly_api_user
    readonly_api_key = str(settings.get("pytestReadonlyApiKey", "")).strip()
    if readonly_api_key:
        env["READONLY_API_KEY"] = readonly_api_key

    logger.info("Running pytest: %s", " ".join(args))

    try:
        proc = subprocess.Popen(
            args,
            cwd=app_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
    except Exception as e:
        logger.exception("Failed to launch pytest")
        return f"Pytest failed to start: {e}"

    if proc.stdout:
        for line in proc.stdout:
            print(line.rstrip())

    code = proc.wait()
    logger.info("Pytest completed with exit code %s", code)

    if code == 0:
        return "Pytest completed successfully."
    return f"Pytest finished with exit code {code}."
