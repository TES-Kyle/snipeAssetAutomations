"""Tests for utilities.partialInstallBuilder's pure population logic.

Uses a fully synthetic fake repo (never the real utilities/Key.py) so this
suite doesn't depend on -- or risk -- whatever real secrets happen to be on
the machine running it. The fixture is a real (if tiny) git repo, since
copy_full_repo() relies on `git ls-files` to decide what to copy.
"""

import ast
import json
import subprocess

import pytest

from utilities import partialInstallBuilder as pib


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def fake_repo(tmp_path):
    """A minimal synthetic git repo: one routing file, two feature modules, Key.py + keyExample.py."""
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.org"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    _write(root / ".gitignore", "utilities/Key.py\nutilities/settings.json\n__pycache__/\nlogs/\n.idea/\n")

    _write(root / "utilities" / "keyExample.py", (
        "API_URL_Base = ''\n"
        "API_Key = ''\n"
        "support_email = ''\n"
        "jamfClientID = ''\n"
        "jamfClientSecret = ''\n"
        "jamfURL = ''\n"
    ))
    _write(root / "utilities" / "Key.py", (
        "API_URL_Base = 'https://example.snipe-it.io/api/v1/'\n"
        "API_Key = 'real-api-key-value'\n"
        "support_email = 'support@example.org'\n"
        "jamfClientID = 'real-jamf-id'\n"
        "jamfClientSecret = 'real-jamf-secret'\n"
        "jamfURL = 'example.jamfcloud.com'\n"
    ))
    _write(root / "utilities" / "otherApiBits.py", (
        "from utilities import Key\n\n"
        "def get_headers():\n"
        "    return {'Authorization': Key.API_URL_Base}\n"
    ))
    _write(root / "utilities" / "api_user.py", (
        "from utilities import Key\n\n"
        "def get_api_key():\n"
        "    return Key.API_Key\n"
    ))
    _write(root / "featureA" / "safe.py", (
        "from utilities.Key import support_email\n\n"
        "def safe_action(tag):\n"
        "    return support_email\n"
    ))
    _write(root / "featureA" / "risky.py", (
        "from utilities import Key\n\n"
        "def risky_action(tag):\n"
        "    return Key.jamfClientID + Key.jamfClientSecret + Key.jamfURL\n"
    ))
    _write(root / "featureA" / "routing.py", (
        "from featureA.safe import safe_action\n"
        "from featureA.risky import risky_action\n\n"
        "func_list = [\n"
        "    safe_action,\n"
        "    risky_action,\n"
        "]\n"
        "func_listTXT = [\n"
        "    'Safe Action',\n"
        "    'Risky (Jamf) Action',\n"
        "]\n"
    ))
    _write(root / "utilities" / "settings.json", '{"leftover": true}\n')

    spec = __import__("utilities.routingCatalog", fromlist=["RoutingFileSpec"]).RoutingFileSpec(
        rel_path="featureA/routing.py", list_var="func_list", labels_var="func_listTXT", group="asset",
    )
    return root, spec


def test_copy_full_repo_never_copies_key_py_or_settings_json(fake_repo, tmp_path):
    root, _ = fake_repo
    dest = tmp_path / "dest"
    pib.copy_full_repo(str(root), str(dest))

    assert not (dest / "utilities" / "Key.py").exists()
    assert not (dest / "utilities" / "settings.json").exists()
    assert (dest / "featureA" / "safe.py").exists()
    assert (dest / "utilities" / "keyExample.py").exists()


def test_copy_full_repo_excludes_git(fake_repo, tmp_path):
    root, _ = fake_repo
    dest = tmp_path / "dest"
    pib.copy_full_repo(str(root), str(dest))
    assert not (dest / ".git").exists()


def test_copy_full_repo_works_from_a_plain_directory_with_no_git_repo(tmp_path):
    # A normal (full) install has no .git at all -- installer.command
    # deliberately strips it (`rsync --exclude ".git"`) when copying a
    # fresh clone into place. Building a partial-install USB from within
    # such an installed app must still work, using the .gitignore that IS
    # still present to decide what to copy.
    root = tmp_path / "installed_app"
    root.mkdir()
    _write(root / ".gitignore", "utilities/Key.py\nutilities/settings.json\nlogs/\n")
    _write(root / "utilities" / "Key.py", "API_Key = 'real-secret'\n")
    _write(root / "utilities" / "keyExample.py", "API_Key = ''\n")
    _write(root / "featureA" / "safe.py", "x = 1\n")
    _write(root / "logs" / "automations.log", "a-real-token-must-not-leak\n")
    assert not (root / ".git").exists()

    dest = tmp_path / "dest"
    pib.copy_full_repo(str(root), str(dest))

    assert (dest / "featureA" / "safe.py").exists()
    assert (dest / "utilities" / "keyExample.py").exists()
    assert not (dest / "utilities" / "Key.py").exists()
    assert not (dest / "logs").exists()
    # The temporary git repo used to interpret .gitignore must be cleaned
    # up afterward -- it must not become a permanent side effect of running
    # this from an installed (non-dev) app.
    assert not (root / ".git").exists()


def test_copy_full_repo_honors_gitignore_for_untracked_cruft(fake_repo, tmp_path):
    """Regression test for the real leak this replaced: a hand-rolled
    directory-name exclusion list didn't know about logs/, so real API
    tokens from DEBUG-level log files ended up on a partial-install USB.
    copy_full_repo must exclude anything .gitignore excludes -- not just a
    fixed list of names guessed up front."""
    root, _ = fake_repo
    (root / "featureA" / "__pycache__").mkdir()
    (root / "featureA" / "__pycache__" / "safe.cpython-314.pyc").write_bytes(b"\x00")
    _write(root / "logs" / "automations.log", "DEBUG a-real-token-must-not-leak-here\n")
    _write(root / ".idea" / "workspace.xml", "<project/>\n")

    dest = tmp_path / "dest"
    pib.copy_full_repo(str(root), str(dest))

    assert not (dest / "featureA" / "__pycache__").exists()
    assert not (dest / "logs").exists()
    assert not (dest / ".idea").exists()


def test_render_trimmed_key_py_includes_only_selected_names_with_real_values(fake_repo):
    root, _ = fake_repo
    rendered = pib.render_trimmed_key_py(str(root), frozenset({"API_URL_Base", "support_email"}), frozenset({"jamfClientID"}))
    ast.parse(rendered)  # must be valid Python
    assert "support@example.org" in rendered
    assert "example.snipe-it.io" in rendered
    assert "real-jamf-id" not in rendered
    assert "jamfClientID" not in rendered.split('"""')[-1]  # not assigned, only maybe mentioned in the docstring header


def test_render_trimmed_key_py_lists_exclusions_in_header(fake_repo):
    root, _ = fake_repo
    rendered = pib.render_trimmed_key_py(str(root), frozenset({"API_URL_Base"}), frozenset({"jamfClientID", "jamfURL"}))
    assert "jamfClientID" in rendered
    assert "jamfURL" in rendered


def test_is_partial_install_false_when_no_manifest(tmp_path):
    root = tmp_path / "app"
    (root / "utilities").mkdir(parents=True)
    assert pib.is_partial_install(str(root)) is False


def test_is_partial_install_true_when_manifest_present(tmp_path):
    root = tmp_path / "app"
    (root / "utilities").mkdir(parents=True)
    _write(root / "utilities" / "partialInstallManifest.json", "{}")
    assert pib.is_partial_install(str(root)) is True


def test_render_manifest_json_shape():
    rendered = pib.render_manifest_json(
        frozenset({"jamfClientID", "jamfURL"}), {"asset": ["Print Selected"]},
    )
    data = json.loads(rendered)
    assert data == {
        "excluded": ["jamfClientID", "jamfURL"],
        "selection": {"asset": ["Print Selected"]},
    }


def test_compute_selection_trace_only_needs_baseline_for_safe_entry(fake_repo):
    root, spec = fake_repo
    from utilities import routingCatalog
    catalog = [e for e in routingCatalog._load_entries_for_spec(spec, str(root))]
    safe_entry = next(e for e in catalog if e.label == "Safe Action")

    selection = {"asset": {safe_entry.index}}
    trace = pib.compute_selection_trace(selection, catalog, str(root))

    assert "API_URL_Base" in trace.key_names  # baseline (otherApiBits.py)
    assert "API_Key" in trace.key_names       # baseline (api_user.py)
    assert "support_email" in trace.key_names  # from the selected entry itself
    assert "jamfClientID" not in trace.key_names


def test_compute_selection_trace_picks_up_jamf_for_risky_entry(fake_repo):
    root, spec = fake_repo
    from utilities import routingCatalog
    catalog = list(routingCatalog._load_entries_for_spec(spec, str(root)))
    risky_entry = next(e for e in catalog if e.label == "Risky (Jamf) Action")

    selection = {"asset": {risky_entry.index}}
    trace = pib.compute_selection_trace(selection, catalog, str(root))

    assert {"jamfClientID", "jamfClientSecret", "jamfURL"} <= trace.key_names


def test_populate_usb_end_to_end_only_writes_selected_secrets(fake_repo, tmp_path):
    root, spec = fake_repo
    from utilities import routingCatalog
    catalog = list(routingCatalog._load_entries_for_spec(spec, str(root)))
    safe_entry = next(e for e in catalog if e.label == "Safe Action")

    usb = tmp_path / "usb"
    usb.mkdir()
    selection = {"asset": {safe_entry.index}}

    # populate_usb loads the real ROUTING_SPECS internally, so point it at
    # our fake repo's single spec by monkeypatching the module list for
    # this call only.
    orig_specs = routingCatalog.ROUTING_SPECS
    routingCatalog.ROUTING_SPECS = (spec,)
    try:
        summary = pib.populate_usb(selection, str(root), str(usb))
    finally:
        routingCatalog.ROUTING_SPECS = orig_specs

    app = usb / "partial_app"
    key_py_text = (app / "utilities" / "Key.py").read_text()
    assert "support@example.org" in key_py_text
    assert "real-jamf-id" not in key_py_text
    assert "real-jamf-secret" not in key_py_text

    manifest = json.loads((app / "utilities" / "partialInstallManifest.json").read_text())
    assert "jamfClientID" in manifest["excluded"]
    assert manifest["selection"] == {"asset": ["Safe Action"]}

    routing_text = (app / "featureA" / "routing.py").read_text()
    assert "safe_action" in routing_text
    assert "risky_action" not in routing_text

    assert "jamfClientID" not in summary["included_key_names"]
    # Nothing written directly at the USB root -- only under partial_app/,
    # so installer.command can tell a partial-install USB apart from a
    # normal one by that directory's presence alone.
    assert not (usb / "utilities").exists()


def test_populate_usb_carries_settings_json_wholesale(fake_repo, tmp_path):
    # settings.json holds low-stakes-but-not-for-public-repo values (e.g.
    # the label printer's IP) -- unlike Key.py it isn't secret-gated by
    # selection, so it must be copied over in full, unconditionally.
    root, spec = fake_repo
    from utilities import routingCatalog
    catalog = list(routingCatalog._load_entries_for_spec(spec, str(root)))
    safe_entry = next(e for e in catalog if e.label == "Safe Action")

    usb = tmp_path / "usb"
    usb.mkdir()
    selection = {"asset": {safe_entry.index}}

    orig_specs = routingCatalog.ROUTING_SPECS
    routingCatalog.ROUTING_SPECS = (spec,)
    try:
        pib.populate_usb(selection, str(root), str(usb))
    finally:
        routingCatalog.ROUTING_SPECS = orig_specs

    settings_path = usb / "partial_app" / "utilities" / "settings.json"
    assert settings_path.exists()
    assert json.loads(settings_path.read_text()) == {"leftover": True}


def test_populate_usb_writes_real_git_sha_to_meta_json(fake_repo, tmp_path):
    root, spec = fake_repo
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)

    from utilities import routingCatalog
    catalog = list(routingCatalog._load_entries_for_spec(spec, str(root)))
    safe_entry = next(e for e in catalog if e.label == "Safe Action")
    usb = tmp_path / "usb"
    usb.mkdir()

    orig_specs = routingCatalog.ROUTING_SPECS
    routingCatalog.ROUTING_SPECS = (spec,)
    try:
        pib.populate_usb({"asset": {safe_entry.index}}, str(root), str(usb))
    finally:
        routingCatalog.ROUTING_SPECS = orig_specs

    meta = json.loads((usb / "partial_app" / ".build" / "meta.json").read_text())
    real_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
    assert meta["installed_sha"] == real_sha
    assert meta["installed_sha"] != "partial-install"


# ---------------------------------------------------------------------------
# update_selection_in_place() and helpers
# ---------------------------------------------------------------------------

def _existing_key_py(tmp_path, **values):
    path = tmp_path / "existing_key.py"
    path.write_text("\n".join(f"{k} = {v!r}" for k, v in values.items()) + "\n")
    return str(path)


def test_labels_to_selection_resolves_by_label_not_index():
    from utilities.routingCatalog import RoutingEntry, RoutingFileSpec
    spec = RoutingFileSpec(rel_path="x.py", list_var="a", labels_var="b", group="asset")
    catalog = [
        RoutingEntry("First", "asset", 0, spec, frozenset({"x.py"})),
        RoutingEntry("Second", "asset", 1, spec, frozenset({"y.py"})),
    ]
    selection, missing = pib._labels_to_selection({"asset": ["Second"]}, catalog)
    assert selection == {"asset": {1}}
    assert missing == []


def test_labels_to_selection_reports_missing_label_without_crashing():
    from utilities.routingCatalog import RoutingEntry, RoutingFileSpec
    spec = RoutingFileSpec(rel_path="x.py", list_var="a", labels_var="b", group="asset")
    catalog = [RoutingEntry("First", "asset", 0, spec, frozenset({"x.py"}))]
    selection, missing = pib._labels_to_selection({"asset": ["Renamed Away"]}, catalog)
    assert selection == {}
    assert missing == ["asset:Renamed Away"]


def test_read_available_key_names_only_returns_non_empty(tmp_path):
    key_py = _existing_key_py(tmp_path, API_Key="real", jamfClientID="", API_KEYS={})
    assert pib._read_available_key_names(key_py) == {"API_Key"}


def test_update_selection_in_place_happy_path_reuses_existing_secrets(fake_repo, tmp_path):
    root, spec = fake_repo
    from utilities import routingCatalog
    orig_specs = routingCatalog.ROUTING_SPECS
    routingCatalog.ROUTING_SPECS = (spec,)
    try:
        existing_key = _existing_key_py(
            tmp_path, API_URL_Base="https://example.snipe-it.io/api/v1/",
            API_Key="real-key", API_KEYS={}, support_email="support@example.org",
        )
        out = tmp_path / "regenerated"
        result = pib.update_selection_in_place(str(root), existing_key, {"asset": ["Safe Action"]}, str(out))
    finally:
        routingCatalog.ROUTING_SPECS = orig_specs

    assert result["missing_labels"] == []
    assert "jamfClientID" not in result["included_key_names"]
    key_py_text = (out / "utilities" / "Key.py").read_text()
    assert "support@example.org" in key_py_text
    routing_text = (out / "featureA" / "routing.py").read_text()
    assert "safe_action" in routing_text
    assert "risky_action" not in routing_text


def test_update_selection_in_place_raises_when_new_secret_needed(fake_repo, tmp_path):
    """The concrete scenario this whole mechanism exists for: upstream code
    now needs a secret this machine was never given. Must refuse loudly
    rather than ship a broken (or worse, silently-wrong) update."""
    root, spec = fake_repo
    from utilities import routingCatalog
    orig_specs = routingCatalog.ROUTING_SPECS
    routingCatalog.ROUTING_SPECS = (spec,)
    try:
        # This machine was only ever given support_email -- selecting the
        # Jamf-needing entry means the update needs secrets it doesn't have.
        existing_key = _existing_key_py(
            tmp_path, API_URL_Base="https://example.snipe-it.io/api/v1/",
            API_Key="real-key", API_KEYS={}, support_email="support@example.org",
        )
        out = tmp_path / "regenerated"
        with pytest.raises(pib.UpdateNeedsRebuild) as exc_info:
            pib.update_selection_in_place(str(root), existing_key, {"asset": ["Risky (Jamf) Action"]}, str(out))
        assert "jamfClientID" in str(exc_info.value)
    finally:
        routingCatalog.ROUTING_SPECS = orig_specs
