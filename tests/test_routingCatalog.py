"""Tests for utilities.routingCatalog (pure AST logic, no Tk/network).

Runs mostly against this repo's real routing files rather than synthetic
fixtures -- the catalog's whole job is parsing *these specific* files
correctly, so testing against fakes would just prove the fakes are simple.
"""

import ast
import importlib.util
import os

import pytest

from utilities import routingCatalog as rc

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _spec_by_group(group):
    return next(s for s in rc.ROUTING_SPECS if s.group == group)


def _exec_rendered(rendered, tmp_path, name):
    path = tmp_path / f"{name}.py"
    path.write_text(rendered)
    mspec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(mspec)
    mspec.loader.exec_module(mod)
    return mod


def test_load_catalog_finds_all_twenty_entries():
    catalog = rc.load_catalog(REPO_ROOT)
    assert len(catalog) == 20
    groups = {e.group for e in catalog}
    assert groups == {"asset", "other", "consisterizer_submit"}


def test_consisterizer_submit_scripts_are_their_own_group_and_require_consisterizer():
    catalog = rc.load_catalog(REPO_ROOT)
    submit_entries = [e for e in catalog if e.group == "consisterizer_submit"]
    labels = {e.label for e in submit_entries}
    assert "Remove PreStage and Delete in Jamf" in labels
    assert "Print Selected" in labels
    spec = _spec_by_group("consisterizer_submit")
    assert spec.requires_label == "Consisterizer"


def test_bulk_checkin_resolves_both_files_it_touches():
    catalog = rc.load_catalog(REPO_ROOT)
    entry = next(e for e in catalog if e.label == "Bulk Check-in")
    assert entry.defining_files == frozenset({
        "consisterizer/consisterizer.py",
        "consisterizer/aliases.py",
    })


def test_jamf_submit_script_traces_to_the_unprestage_module():
    catalog = rc.load_catalog(REPO_ROOT)
    entry = next(e for e in catalog if e.label == "Remove PreStage and Delete in Jamf")
    assert entry.defining_files == frozenset({"assetManagementFunctions/jamfDeleteAndUnprestage.py"})


def test_render_trimmed_asset_routing_file_keeps_only_selected_entries(tmp_path):
    spec = _spec_by_group("asset")
    rendered = rc.render_trimmed_routing_file(REPO_ROOT, spec, [0, 8])  # Print Selected, Check In
    ast.parse(rendered)  # must be valid Python
    mod = _exec_rendered(rendered, tmp_path, "trimmed_asset_routing")
    assert mod.func_listTXT == ["Print Selected", "Check In"]
    assert len(mod.func_list) == 2
    assert all(callable(f) for f in mod.func_list)


def test_render_trimmed_file_drops_unused_imports(tmp_path):
    spec = _spec_by_group("asset")
    rendered = rc.render_trimmed_routing_file(REPO_ROOT, spec, [0])  # Print Selected only
    assert "newRepair" not in rendered
    assert "jamfDeleteAndUnprestage" not in rendered
    assert "printSelected" in rendered


def test_render_trimmed_file_with_zero_selected_entries_is_valid_and_empty(tmp_path):
    spec = _spec_by_group("consisterizer_submit")
    rendered = rc.render_trimmed_routing_file(REPO_ROOT, spec, [])
    ast.parse(rendered)
    mod = _exec_rendered(rendered, tmp_path, "trimmed_empty_routing")
    assert mod.submit_func_list == []
    assert mod.submit_func_listTXT == []


def test_render_trimmed_file_with_all_entries_matches_original_count(tmp_path):
    spec = _spec_by_group("other")
    all_indices = range(3)
    rendered = rc.render_trimmed_routing_file(REPO_ROOT, spec, all_indices)
    mod = _exec_rendered(rendered, tmp_path, "trimmed_full_other_routing")
    assert len(mod.other_func_list) == 3
    assert mod.other_func_listTXT == ["Sync Jamf Asset Tags", "Sync Snipe Battery Data", "Connected Charger Data"]


def test_malformed_routing_file_raises_parse_error(tmp_path):
    (tmp_path / "utilities").mkdir()
    fake = tmp_path / "fake_routing.py"
    fake.write_text("func_list = [1, 2]\nfunc_listTXT = ['only one']\n")
    bad_spec = rc.RoutingFileSpec(
        rel_path="fake_routing.py", list_var="func_list", labels_var="func_listTXT", group="asset",
    )
    with pytest.raises(rc.RoutingFileParseError):
        rc.render_trimmed_routing_file(str(tmp_path), bad_spec, [0])
