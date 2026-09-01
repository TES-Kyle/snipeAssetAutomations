"""Intercept utilities.Key import to fail gracefully if Key.py is missing or broken."""

import importlib.util
import json
import logging
import os
import sys
import types

logger = logging.getLogger(__name__)

_dir = os.path.dirname(__file__)

# --- Load keyExample.py to get the canonical list of expected variables ---
# This is the single source of truth for what Key.py should contain.
_example_path = os.path.join(_dir, 'keyExample.py')
_example_vars = {}  # name -> type-appropriate empty default
logger.debug("__init__: loading keyExample.py from %s", _example_path)
try:
    _ex_spec = importlib.util.spec_from_file_location('utilities._key_example', _example_path)
    _ex_module = importlib.util.module_from_spec(_ex_spec)
    _ex_spec.loader.exec_module(_ex_module)
    for _k, _v in vars(_ex_module).items():
        if not _k.startswith('_'):
            _example_vars[_k] = {} if isinstance(_v, dict) else [] if isinstance(_v, list) else ''
    logger.debug("__init__: keyExample.py loaded, %s expected vars", len(_example_vars))
except Exception as _exc:
    logger.warning("Could not load keyExample.py for credential validation: %s", _exc)

# --- Pre-register a safe Key module with empty defaults ---
# Python returns this object from sys.modules for any
# "from utilities import Key" or "from utilities.Key import ..." call.
logger.debug("__init__: pre-registering safe Key module with %s empty defaults", len(_example_vars))
_key_module = types.ModuleType('utilities.Key')
_key_module.__package__ = 'utilities'
_key_module.SECRETS_LOAD_ERROR = ''
for _k, _v in _example_vars.items():
    setattr(_key_module, _k, _v)
sys.modules['utilities.Key'] = _key_module
logger.debug("__init__: safe Key module registered in sys.modules")

# --- Try to load the real Key.py content into the module ---
_key_path = os.path.join(_dir, 'Key.py')
logger.debug("__init__: attempting to load Key.py from %s", _key_path)
try:
    _spec = importlib.util.spec_from_file_location('utilities.Key', _key_path)
    logger.debug("__init__: Key.py spec created; executing module")
    _spec.loader.exec_module(_key_module)
    logger.info("utilities.Key loaded successfully")
except FileNotFoundError:
    _key_module.SECRETS_LOAD_ERROR = (
        "utilities/Key.py not found — restore it and fill in credentials."
    )
    logger.error(_key_module.SECRETS_LOAD_ERROR)
    logger.debug("__init__: Key.py not found at %s; safe defaults remain active", _key_path)
except SyntaxError as exc:
    _key_module.SECRETS_LOAD_ERROR = f"utilities/Key.py has a syntax error: {exc}"
    logger.error(_key_module.SECRETS_LOAD_ERROR)
    logger.debug("__init__: Key.py has SyntaxError; safe defaults remain active")
except Exception as exc:
    _key_module.SECRETS_LOAD_ERROR = f"Unexpected error loading utilities/Key.py: {exc}"
    logger.error(_key_module.SECRETS_LOAD_ERROR)
    logger.debug("__init__: unexpected error loading Key.py: %s; safe defaults remain active", exc)

# --- Partial installs intentionally ship a Key.py with some names blank ---
# A trimmed Key.py (see utilities/keyDependencyGraph.py / partialInstallBuilder.py)
# omits secrets the selected modules don't need. Without this, the validation
# below would flag every one of those as "missing" and show a scary
# Configuration Error dialog on every launch of an intentionally partial
# install. Normal installs never have this file, so their behavior here is
# unchanged.
_manifest_path = os.path.join(_dir, 'partialInstallManifest.json')
_intentionally_excluded = set()
if os.path.isfile(_manifest_path):
    try:
        with open(_manifest_path, 'r', encoding='utf-8') as _mf:
            _intentionally_excluded = set(json.load(_mf).get('excluded', []))
        logger.debug("__init__: partialInstallManifest.json found, %s intentionally excluded vars", len(_intentionally_excluded))
    except Exception as _exc:
        logger.warning("Could not read partialInstallManifest.json: %s", _exc)

# --- Compare Key.py variables against keyExample.py ---
# Only run when the file loaded without errors and we have an example to compare against.
logger.debug("__init__: SECRETS_LOAD_ERROR=%s, will validate=%s",
             bool(_key_module.SECRETS_LOAD_ERROR), bool(not _key_module.SECRETS_LOAD_ERROR and _example_vars))
if not _key_module.SECRETS_LOAD_ERROR and _example_vars:
    _expected = set(_example_vars)
    _actual = {k for k in vars(_key_module) if not k.startswith('_') and k != 'SECRETS_LOAD_ERROR'}
    logger.debug("__init__: expected vars=%s, actual vars=%s", len(_expected), len(_actual))

    # In example but missing or empty in Key.py — credentials need to be filled in.
    # Vars intentionally left blank for a partial install don't count.
    _missing = sorted(k for k in _expected if not getattr(_key_module, k, None) and k not in _intentionally_excluded)
    # In Key.py but not in example — keyExample.py needs to be updated.
    _undocumented = sorted(_actual - _expected)
    logger.debug("__init__: missing vars=%s, undocumented vars=%s", _missing, _undocumented)

    _issues = []
    if _missing:
        _issues.append("Key.py is missing or has empty values for: " + ", ".join(_missing))
        logger.debug("__init__: missing credential variables: %s", _missing)
    if _undocumented:
        _issues.append("keyExample.py is out of date, add these variables: " + ", ".join(_undocumented))
        logger.debug("__init__: undocumented variables (not in keyExample.py): %s", _undocumented)

    if _issues:
        _key_module.SECRETS_LOAD_ERROR = "\n\n".join(_issues)
        logger.error(_key_module.SECRETS_LOAD_ERROR)
    else:
        logger.debug("__init__: Key.py validation passed; all expected vars present")
