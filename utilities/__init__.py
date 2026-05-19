"""Intercept utilities.Key import to fail gracefully if Key.py is missing or broken."""

import importlib.util
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
try:
    _ex_spec = importlib.util.spec_from_file_location('utilities._key_example', _example_path)
    _ex_module = importlib.util.module_from_spec(_ex_spec)
    _ex_spec.loader.exec_module(_ex_module)
    for _k, _v in vars(_ex_module).items():
        if not _k.startswith('_'):
            _example_vars[_k] = {} if isinstance(_v, dict) else [] if isinstance(_v, list) else ''
except Exception as _exc:
    logger.warning("Could not load keyExample.py for credential validation: %s", _exc)

# --- Pre-register a safe Key module with empty defaults ---
# Python returns this object from sys.modules for any
# "from utilities import Key" or "from utilities.Key import ..." call.
_key_module = types.ModuleType('utilities.Key')
_key_module.__package__ = 'utilities'
_key_module.SECRETS_LOAD_ERROR = ''
for _k, _v in _example_vars.items():
    setattr(_key_module, _k, _v)
sys.modules['utilities.Key'] = _key_module

# --- Try to load the real Key.py content into the module ---
_key_path = os.path.join(_dir, 'Key.py')
try:
    _spec = importlib.util.spec_from_file_location('utilities.Key', _key_path)
    _spec.loader.exec_module(_key_module)
except FileNotFoundError:
    _key_module.SECRETS_LOAD_ERROR = (
        "utilities/Key.py not found — restore it and fill in credentials."
    )
    logger.error(_key_module.SECRETS_LOAD_ERROR)
except SyntaxError as exc:
    _key_module.SECRETS_LOAD_ERROR = f"utilities/Key.py has a syntax error: {exc}"
    logger.error(_key_module.SECRETS_LOAD_ERROR)
except Exception as exc:
    _key_module.SECRETS_LOAD_ERROR = f"Unexpected error loading utilities/Key.py: {exc}"
    logger.error(_key_module.SECRETS_LOAD_ERROR)

# --- Compare Key.py variables against keyExample.py ---
# Only run when the file loaded without errors and we have an example to compare against.
if not _key_module.SECRETS_LOAD_ERROR and _example_vars:
    _expected = set(_example_vars)
    _actual = {k for k in vars(_key_module) if not k.startswith('_') and k != 'SECRETS_LOAD_ERROR'}

    # In example but missing or empty in Key.py — credentials need to be filled in.
    _missing = sorted(k for k in _expected if not getattr(_key_module, k, None))
    # In Key.py but not in example — keyExample.py needs to be updated.
    _undocumented = sorted(_actual - _expected)

    _issues = []
    if _missing:
        _issues.append("Key.py is missing or has empty values for: " + ", ".join(_missing))
    if _undocumented:
        _issues.append("keyExample.py is out of date, add these variables: " + ", ".join(_undocumented))

    if _issues:
        _key_module.SECRETS_LOAD_ERROR = "\n\n".join(_issues)
        logger.error(_key_module.SECRETS_LOAD_ERROR)
