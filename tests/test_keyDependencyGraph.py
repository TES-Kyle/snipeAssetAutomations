"""Tests for utilities.keyDependencyGraph (pure AST logic, no Tk/network).

Mixes isolated synthetic-fixture tests (via tmp_path) with a few tests run
directly against this repo's real files -- the latter double as regression
guards for the concrete findings that shaped the partial-install design
(chargerSerial.py's non-obvious Jamf dependency, api_retry.py's docstring
mention of jamfPrestageCommon that must NOT be treated as a real import).
"""

import os

import pytest

from utilities import keyDependencyGraph as kdg

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_KNOWN = frozenset({"support_email", "jamfURL", "jamfClientID", "jamfClientSecret", "windmillToken", "API_Key"})


def _write(tmp_path, rel_path, content):
    path = tmp_path / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_bare_key_import_is_found(tmp_path):
    _write(tmp_path, "pkg/mod.py", "from utilities.Key import support_email\n")
    trace = kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)
    assert trace.key_names == {"support_email"}


def test_module_style_key_attribute_access_is_found(tmp_path):
    _write(tmp_path, "pkg/mod.py", "from utilities import Key\n\nurl = Key.jamfURL\n")
    trace = kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)
    assert trace.key_names == {"jamfURL"}


def test_getattr_literal_access_is_found(tmp_path):
    _write(tmp_path, "pkg/mod.py", "from utilities import Key\n\nk = getattr(Key, 'API_Key', '')\n")
    trace = kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)
    assert trace.key_names == {"API_Key"}


def test_getattr_with_non_literal_name_is_not_falsely_matched(tmp_path):
    # A dynamic (non-string-literal) getattr can't be resolved statically --
    # it should be silently skipped, not crash or invent a key name.
    _write(tmp_path, "pkg/mod.py", "from utilities import Key\n\nname = 'API_Key'\nk = getattr(Key, name, '')\n")
    trace = kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)
    assert trace.key_names == set()


def test_local_import_is_followed_transitively(tmp_path):
    _write(tmp_path, "pkgA/entry.py", "from pkgB.helper import do_it\n")
    _write(tmp_path, "pkgB/helper.py", "from utilities.Key import windmillToken\n\ndef do_it():\n    pass\n")
    trace = kdg.trace_module("pkgA/entry.py", str(tmp_path), known_key_names=_KNOWN)
    assert trace.key_names == {"windmillToken"}
    assert trace.files == {"pkgA/entry.py", "pkgB/helper.py"}


def test_external_imports_are_ignored(tmp_path):
    _write(tmp_path, "pkg/mod.py", "import requests\nimport os\nfrom tkinter import messagebox\n")
    trace = kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)
    assert trace.key_names == set()
    assert trace.files == {"pkg/mod.py"}


def test_docstring_mention_of_a_module_does_not_trigger_a_local_import():
    # utilities/api_retry.py's docstring mentions utilities.jamfPrestageCommon
    # in prose, without ever importing it -- this is the concrete case that
    # ruled out a text-search-based tracer in favor of AST parsing.
    trace = kdg.trace_module("utilities/api_retry.py", REPO_ROOT)
    assert "utilities/jamfPrestageCommon.py" not in trace.files
    assert not trace.key_names & {"jamfClientID", "jamfClientSecret", "jamfURL"}


def test_unresolved_local_import_raises(tmp_path):
    _write(tmp_path, "pkg/mod.py", "from pkg.does_not_exist import thing\n")
    with pytest.raises(kdg.UnresolvedImportError):
        kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)


def test_unknown_key_name_raises(tmp_path):
    _write(tmp_path, "pkg/mod.py", "from utilities.Key import totallyMadeUpSecretName\n")
    with pytest.raises(kdg.UnknownKeyNameError):
        kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)


def test_import_utilities_key_form_raises_actionable_error(tmp_path):
    _write(tmp_path, "pkg/mod.py", "import utilities.Key\n")
    with pytest.raises(kdg.UnresolvedImportError):
        kdg.trace_module("pkg/mod.py", str(tmp_path), known_key_names=_KNOWN)


def test_load_known_key_names_matches_real_keyExample():
    names = kdg.load_known_key_names(REPO_ROOT)
    assert "jamfClientID" in names
    assert "API_URL_Base" in names
    assert "_" not in "".join(n[0] for n in names)  # no private/underscore-prefixed names leaked in


def test_chargerSerial_needs_jamf_secrets():
    # "Check Charger History" isn't obviously Jamf-related from its label --
    # this is the concrete finding that justified static-analysis-derived
    # dependency tracing over a hand-maintained mapping.
    trace = kdg.trace_module("assetManagementFunctions/chargerSerial.py", REPO_ROOT)
    assert {"jamfClientID", "jamfClientSecret", "jamfURL"} <= trace.key_names


def test_printSelected_does_not_need_jamf_secrets():
    trace = kdg.trace_module("assetManagementFunctions/printSelected.py", REPO_ROOT)
    assert not trace.key_names & {"jamfClientID", "jamfClientSecret", "jamfURL"}


def test_trace_selection_always_includes_baseline_infra():
    trace = kdg.trace_selection([], REPO_ROOT)
    assert {"API_URL_Base", "API_Key", "API_KEYS"} <= trace.key_names
    for baseline_file in kdg.BASELINE_INFRA_FILES:
        assert baseline_file in trace.files
