"""Partial-install USB builder: selection UI + trimmed-payload writer.

Lets an admin pick a subset of the 20 selectable entries across all three
routing tables (utilities/routingCatalog.py) and write a USB stick carrying
the full app source, a Key.py trimmed to only the secrets those entries
actually need (utilities/keyDependencyGraph.py), and routing tables trimmed
to only the selected entries.

No intermediate staging folder -- the trimmed payload is written directly
onto the freshly erased/mounted USB volume. Disk selection/erase/mount and
the final installer.command+icon copy/eject are handled by two small shell
scripts this module shells out to (shellScripts/select_and_erase_usb.command,
shellScripts/finalize_usb.command) -- the same scripts make_installer_usb.command
itself calls for a normal full install, so both paths share one
tested disk-handling implementation.

The population logic below (populate_usb and everything it calls) has no Tk
dependency and is fully unit-testable; only open_partial_install_builder()
and its nested callbacks touch Tk, matching this codebase's convention of
not unit-testing window-building code.
"""

import datetime
import json
import logging
import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from utilities import keyDependencyGraph, routingCatalog

logger = logging.getLogger(__name__)

# Redundant, explicit exclusion for the one file whose leak would actually
# matter -- on top of (not instead of) the .gitignore-driven exclusion in
# copy_full_repo(), in case .gitignore is ever edited to drop that line.
_NEVER_COPY_REL_FILES = frozenset({"utilities/Key.py", "utilities/settings.json"})


def is_partial_install(repo_root: str) -> bool:
    """Return True if repo_root is a partial (not full) install.

    Same detection utilities/__init__.py and update_in_place.command
    already use: a partial install carries utilities/partialInstallManifest.json,
    a normal install never does.

    Args:
        repo_root: Absolute path to the app's root directory.

    Returns:
        True if this install is a partial install.
    """
    return os.path.isfile(os.path.join(repo_root, "utilities", "partialInstallManifest.json"))

_SELECT_SCRIPT = "shellScripts/select_and_erase_usb.command"
_FINALIZE_SCRIPT = "shellScripts/finalize_usb.command"
_OFFER_EJECT_SCRIPT = "shellScripts/offer_eject.command"
_USER_CANCELLED_EXIT_CODE = 2


class BuildCancelled(Exception):
    """The admin cancelled disk selection/erase."""


class UpdateNeedsRebuild(Exception):
    """Fresh code needs a secret this installation does not already have.

    There is no way to get a new secret onto an already-deployed partial
    install except a fresh USB build -- update_selection_in_place() raises
    this instead of silently shipping a broken update.
    """


# ---------------------------------------------------------------------------
# Pure population logic -- no Tk, fully testable
# ---------------------------------------------------------------------------

def compute_selection_trace(selection: dict, catalog: list, repo_root: str):
    """Trace every selected catalog entry's Key.py needs.

    Args:
        selection: {group: set(index)} of selected entries, e.g.
            {"asset": {0, 10}, "other": set(), "consisterizer_submit": set()}.
        catalog: Result of routingCatalog.load_catalog(repo_root).
        repo_root: Absolute path to the repository root.

    Returns:
        keyDependencyGraph.ModuleTrace for the union of selected entries
        plus the always-included baseline infra.
    """
    defining_files = set()
    for entry in catalog:
        if entry.index in selection.get(entry.group, set()):
            defining_files |= entry.defining_files
    # Routing-table files are selection boundaries, not just files to walk
    # through: consisterizer.py unconditionally imports
    # consisterizerScriptsRouting.py (to build its own submit-checkbox
    # list), which in turn imports every one of THOSE entries' targets --
    # without this, selecting "Consisterizer" alone would always drag in
    # whatever consisterizer_submit's entries need (including Jamf),
    # regardless of whether that specific submit-script was selected. Each
    # routing table's own entries are already traced independently via the
    # defining_files loop above, driven by their own group's selection.
    stop_at_files = frozenset(spec.rel_path for spec in routingCatalog.ROUTING_SPECS)
    return keyDependencyGraph.trace_selection(defining_files, repo_root, stop_at_files=stop_at_files)


def render_trimmed_key_py(
    repo_root: str, included_names: frozenset, excluded_names: frozenset, source_key_py_path: str = None,
) -> str:
    """Return trimmed Key.py source: real values for included names only.

    Values come from executing a Key.py and reading back its attributes --
    same mechanic settingsMenu.py's Sync Key already uses -- so string
    escaping/dict formatting is handled by Python's own repr(), not
    re-implemented here.

    Args:
        repo_root: Absolute path to the repository root (used to order the
            output and, unless source_key_py_path is given, to locate the
            source Key.py too).
        included_names: Key.py variable names to include with real values.
        excluded_names: Names intentionally omitted (for the header comment
            only -- the actual exclusion is just not writing the line).
        source_key_py_path: Path to the Key.py to read real values from.
            Defaults to repo_root/utilities/Key.py -- the admin's own full
            Key.py, used when building a fresh partial install. Refreshing
            an already-installed partial install instead passes that
            machine's own already-trimmed Key.py here, since a full one is
            never present there -- see update_selection_in_place().

    Returns:
        Full source text for the trimmed Key.py.
    """
    import importlib.util

    if source_key_py_path is None:
        source_key_py_path = os.path.join(repo_root, "utilities", "Key.py")
    spec = importlib.util.spec_from_file_location("_partial_install_source_key", source_key_py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ordered_names = [n for n in _key_example_declaration_order(repo_root) if n in included_names]
    generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        '"""Trimmed Key.py for a partial install.',
        "",
        f"Generated {generated_at} by utilities/partialInstallBuilder.py.",
        "Names intentionally left out of this file (see partialInstallManifest.json,",
        "which utilities/__init__.py checks so this doesn't show as a configuration",
        "error on this machine):",
        f"  {', '.join(sorted(excluded_names)) or '(none)'}",
        '"""',
        "",
    ]
    for name in ordered_names:
        lines.append(f"{name} = {getattr(mod, name)!r}")
    return "\n".join(lines) + "\n"


def render_manifest_json(excluded_names: frozenset, selection_labels: dict) -> str:
    """Return the JSON body for utilities/partialInstallManifest.json.

    Args:
        excluded_names: Key.py variable names intentionally left blank --
            the only key utilities/__init__.py actually reads today.
        selection_labels: {group: [label, ...]} of what was selected, by
            label rather than routing-table index so it stays meaningful
            even if entries get added/reordered later. Not consumed by
            anything yet -- persisted so a future "rebuild this same
            selection against newer code" update path has what it needs,
            without having to guess the original selection back out of a
            Key.py that's already been trimmed.

    Returns:
        JSON text for utilities/partialInstallManifest.json.
    """
    return json.dumps(
        {"excluded": sorted(excluded_names), "selection": selection_labels},
        indent=2,
    ) + "\n"


def copy_full_repo(repo_root: str, dest_root: str):
    """Copy the project's current working-tree contents to dest_root.

    What to copy is determined by `git ls-files --cached --others
    --exclude-standard` -- every tracked file plus every untracked-but-not-
    ignored file, i.e. exactly what `git add -A` would pick up. This
    piggybacks on the project's own .gitignore as the single source of
    truth for "local-only, never distributed" (logs/, .idea/, __pycache__/,
    .venv/, utilities/Key.py, utilities/settings.json, ...) instead of a
    second, hand-maintained exclusion list that can silently miss things --
    which is exactly what happened the first time this ran: a hand-rolled
    directory-name list here didn't know about logs/, and real API tokens
    from DEBUG-level log files ended up on a partial-install USB.

    utilities/Key.py and utilities/settings.json are ALSO excluded
    explicitly at the rsync level, redundantly on top of .gitignore --
    defense in depth for the one file whose leak would actually matter.

    Copies via rsync (not Python's shutil): shutil.copy2's macOS fast-copy
    path (fcopyfile) can raise OSError: [Errno 22] Invalid argument when
    writing to certain external volume formats -- seen in practice writing
    to a JHFS+-formatted USB stick. installer.command already uses rsync
    for the equivalent full-tree copy elsewhere in this app and doesn't hit
    this, so this matches that instead of re-solving it a different way.

    Args:
        repo_root: Absolute path to the repository root (source). Does not
            need to already be a git working tree -- see below.
        dest_root: Absolute path to copy into (e.g. the mounted USB volume).

    Raises:
        RuntimeError: git or rsync failed.
    """
    os.makedirs(dest_root, exist_ok=True)

    # installer.command deliberately strips .git out of a normal (full)
    # install (`rsync --exclude ".git"`), so an app running from an
    # ordinary installed copy has no working tree here at all -- only a dev
    # checkout does. git ls-files needs SOME working tree to interpret
    # .gitignore against, so temporarily init one in place (repo_root's own
    # .gitignore is still present -- only .git itself was stripped) and
    # remove it again immediately after. Purely local and reversible: no
    # commit, no remote, nothing written outside repo_root/.git, and it's
    # torn down in the same call before this function returns.
    made_temp_git_dir = False
    if not os.path.isdir(os.path.join(repo_root, ".git")):
        init_proc = subprocess.run(["git", "init", "-q"], cwd=repo_root, capture_output=True)
        if init_proc.returncode != 0:
            raise RuntimeError(
                f"git init failed in {repo_root}: {init_proc.stderr.decode(errors='replace').strip()}"
            )
        made_temp_git_dir = True

    try:
        git_proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=repo_root, capture_output=True,
        )
        if git_proc.returncode != 0:
            raise RuntimeError(
                f"git ls-files failed in {repo_root} (is it a git working tree?): "
                f"{git_proc.stderr.decode(errors='replace').strip()}"
            )
    finally:
        if made_temp_git_dir:
            import shutil
            shutil.rmtree(os.path.join(repo_root, ".git"), ignore_errors=True)

    exclude_args = []
    for rel_file in sorted(_NEVER_COPY_REL_FILES):
        exclude_args += ["--exclude", rel_file]

    # --files-from=- reads the NUL-separated list from stdin (matching git
    # ls-files -z's own output format) and copies exactly those paths,
    # preserving directory structure. No --delete: dest_root is always a
    # freshly created directory here, nothing to reconcile against.
    rsync_proc = subprocess.run(
        ["rsync", "-a", "--from0", "--files-from=-", *exclude_args,
         f"{repo_root.rstrip('/')}/", f"{dest_root.rstrip('/')}/"],
        input=git_proc.stdout, capture_output=True,
    )
    if rsync_proc.returncode != 0:
        raise RuntimeError(
            f"rsync failed copying {repo_root} -> {dest_root}: "
            f"{rsync_proc.stderr.decode(errors='replace').strip()}"
        )
    logger.info("copy_full_repo: copied %s -> %s via git ls-files + rsync", repo_root, dest_root)


def populate_usb(selection: dict, repo_root: str, usb_mount: str) -> dict:
    """Write the complete trimmed partial-install payload onto a mounted USB.

    Args:
        selection: {group: set(index)} of selected entries.
        repo_root: Absolute path to the repository root.
        usb_mount: Absolute path to the mounted USB volume.

    Returns:
        Summary dict: {"included_key_names": frozenset, "excluded_key_names":
        frozenset, "file_count": int}.
    """
    catalog = routingCatalog.load_catalog(repo_root)
    known_names = keyDependencyGraph.load_known_key_names(repo_root)
    trace = compute_selection_trace(selection, catalog, repo_root)
    excluded_names = known_names - trace.key_names

    logger.info(
        "populate_usb: %s entries selected, %s key names included, %s excluded",
        sum(len(v) for v in selection.values()), len(trace.key_names), len(excluded_names),
    )

    # Nested under partial_app/ (not the USB root, where installer.command
    # and optional loose Key.py/settings.json/icon.icns already live for a
    # normal full install) -- installer.command detects this directory's
    # presence to decide whether to use this pre-built payload instead of
    # its usual `git clone`.
    app_dest = os.path.join(usb_mount, "partial_app")
    copy_full_repo(repo_root, app_dest)

    _write(os.path.join(app_dest, "utilities", "Key.py"),
           render_trimmed_key_py(repo_root, trace.key_names, excluded_names))
    _write(os.path.join(app_dest, "utilities", "partialInstallManifest.json"),
           render_manifest_json(excluded_names, _selection_labels(selection, catalog)))

    # settings.json isn't secret-gated like Key.py -- it's low-stakes values
    # (e.g. the label printer's IP) the admin just doesn't want in the
    # public repo. copy_full_repo() above never carries it (it's gitignored,
    # and also redundantly listed in _NEVER_COPY_REL_FILES), so it has to be
    # copied wholesale here, same as a full install's optional
    # SETTINGS_SRC_JSON step in make_installer_usb.command/installer.command.
    # Read+write manually rather than shutil.copy2 -- copy2's macOS
    # fast-copy syscall path is what caused the [Errno 22] failure writing
    # to this same JHFS+ USB earlier (see copy_full_repo's rsync switch).
    settings_src = os.path.join(repo_root, "utilities", "settings.json")
    if os.path.isfile(settings_src):
        with open(settings_src, "r", encoding="utf-8") as f:
            _write(os.path.join(app_dest, "utilities", "settings.json"), f.read())

    for spec in routingCatalog.ROUTING_SPECS:
        indices = selection.get(spec.group, set())
        rendered = routingCatalog.render_trimmed_routing_file(repo_root, spec, indices)
        _write(os.path.join(app_dest, *spec.rel_path.split("/")), rendered)

    # The admin's actual git state at build time -- not the literal string
    # "partial-install" -- so checkUpdate() on the target machine can tell
    # whether a real update is available instead of always claiming one is.
    # installer.command keeps this file as-is when present rather than
    # generating its own.
    _write(os.path.join(app_dest, ".build", "meta.json"), json.dumps({
        "repo_url": _current_git_remote_url(repo_root),
        "branch": _current_git_branch(repo_root),
        "installed_sha": _current_git_sha(repo_root),
        "last_checked": "",
    }, indent=2) + "\n")

    return {
        "included_key_names": trace.key_names,
        "excluded_key_names": frozenset(excluded_names),
        "file_count": len(trace.files),
    }


def update_selection_in_place(
    fresh_repo_root: str, existing_key_py_path: str, selection_labels: dict, output_dir: str,
) -> dict:
    """Re-derive a trimmed payload for the SAME selection against fresh code.

    Used by update_in_place.command to refresh an already-installed
    partial install without ever needing the original admin's full Key.py
    -- only whatever subset of secrets is already present on this machine.
    Writes to output_dir rather than touching the live install directly;
    the caller (which already has an admin-privilege-aware copy mechanism)
    moves the results into place.

    Args:
        fresh_repo_root: Absolute path to the freshly cloned repo.
        existing_key_py_path: Path to this machine's own, already-trimmed
            Key.py.
        selection_labels: {group: [label, ...]} read back from this
            machine's utilities/partialInstallManifest.json.
        output_dir: Where to write the regenerated Key.py/manifest/routing
            files.

    Returns:
        Summary dict: {"missing_labels": [...], "included_key_names":
        frozenset, "excluded_key_names": frozenset}.

    Raises:
        UpdateNeedsRebuild: The fresh code needs a secret this installation
            does not already have.
    """
    catalog = routingCatalog.load_catalog(fresh_repo_root)
    selection, missing_labels = _labels_to_selection(selection_labels, catalog)
    known_names = keyDependencyGraph.load_known_key_names(fresh_repo_root)
    trace = compute_selection_trace(selection, catalog, fresh_repo_root)
    available_names = _read_available_key_names(existing_key_py_path)

    missing_secrets = trace.key_names - available_names
    if missing_secrets:
        raise UpdateNeedsRebuild(
            "This update needs secrets not already present on this installation: "
            + ", ".join(sorted(missing_secrets))
        )

    excluded_names = known_names - trace.key_names
    os.makedirs(output_dir, exist_ok=True)
    _write(os.path.join(output_dir, "utilities", "Key.py"),
           render_trimmed_key_py(fresh_repo_root, trace.key_names, excluded_names,
                                  source_key_py_path=existing_key_py_path))
    _write(os.path.join(output_dir, "utilities", "partialInstallManifest.json"),
           render_manifest_json(excluded_names, _selection_labels(selection, catalog)))

    for spec in routingCatalog.ROUTING_SPECS:
        indices = selection.get(spec.group, set())
        rendered = routingCatalog.render_trimmed_routing_file(fresh_repo_root, spec, indices)
        _write(os.path.join(output_dir, *spec.rel_path.split("/")), rendered)

    logger.info(
        "update_selection_in_place: %s key names included, %s excluded, %s missing labels",
        len(trace.key_names), len(excluded_names), len(missing_labels),
    )
    return {
        "missing_labels": missing_labels,
        "included_key_names": trace.key_names,
        "excluded_key_names": frozenset(excluded_names),
    }


def _labels_to_selection(selection_labels: dict, catalog: list):
    """Resolve {group: [label, ...]} back to {group: {index, ...}} against catalog.

    Labels are the stable identity persisted in the manifest -- indices can
    shift if a routing table is reordered or gains new entries. Any label
    that no longer exists in the given catalog (e.g. renamed or removed
    upstream) is dropped from the resolved selection and reported back via
    missing_labels rather than treated as fatal: losing one now-nonexistent
    function should not block updating everything else that is still valid.

    Args:
        selection_labels: {group: [label, ...]}.
        catalog: Result of routingCatalog.load_catalog() to resolve against.

    Returns:
        (selection, missing_labels): selection is {group: {index, ...}};
        missing_labels is a list of "group:label" strings for labels not
        found in catalog.
    """
    by_group_label = {(entry.group, entry.label): entry.index for entry in catalog}
    selection = {}
    missing_labels = []
    for group, labels in selection_labels.items():
        for label in labels:
            index = by_group_label.get((group, label))
            if index is None:
                missing_labels.append(f"{group}:{label}")
            else:
                selection.setdefault(group, set()).add(index)
    return selection, missing_labels


def _read_available_key_names(key_py_path: str) -> frozenset:
    """Return the set of Key.py variable names with a real (non-empty) value at this path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_partial_install_available_key", key_py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return frozenset(k for k, v in vars(mod).items() if not k.startswith("_") and v)


def _current_git_sha(repo_root: str) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def _current_git_branch(repo_root: str) -> str:
    proc = subprocess.run(["git", "branch", "--show-current"], cwd=repo_root, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "main"


def _current_git_remote_url(repo_root: str) -> str:
    proc = subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo_root, capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def run_select_and_erase(repo_root: str) -> str:
    """Run the disk-select/erase/mount script and return the mounted path.

    Raises:
        BuildCancelled: The admin cancelled disk selection.
        RuntimeError: The script failed for any other reason.
    """
    script = os.path.join(repo_root, *_SELECT_SCRIPT.split("/"))
    logger.info("run_select_and_erase: launching %s", script)
    proc = subprocess.run(["bash", script], capture_output=True, text=True)
    logger.info(
        "run_select_and_erase: exit=%s stdout=%r stderr=%r",
        proc.returncode, proc.stdout.strip(), proc.stderr.strip(),
    )
    if proc.returncode == _USER_CANCELLED_EXIT_CODE:
        raise BuildCancelled()
    if proc.returncode != 0:
        raise RuntimeError(f"{_SELECT_SCRIPT} failed (exit {proc.returncode}): {proc.stderr.strip()}")
    mount_path = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    if not mount_path or not os.path.isdir(mount_path):
        raise RuntimeError(f"{_SELECT_SCRIPT} did not report a valid mounted path (got: {mount_path!r})")
    return mount_path


def run_finalize(repo_root: str, usb_mount: str):
    """Run the finalize script (copy installer.command + icon, clear quarantine).

    Deliberately does not offer to eject -- see run_offer_eject(), called
    separately, later, after the success summary has had a chance to show.
    """
    script = os.path.join(repo_root, *_FINALIZE_SCRIPT.split("/"))
    proc = subprocess.run(["bash", script, usb_mount], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"{_FINALIZE_SCRIPT} failed (exit {proc.returncode}): {proc.stderr.strip()}")


def run_offer_eject(repo_root: str, usb_mount: str):
    """Run the eject-prompt script. Best-effort -- failures here don't fail the build."""
    script = os.path.join(repo_root, *_OFFER_EJECT_SCRIPT.split("/"))
    proc = subprocess.run(["bash", script, usb_mount], capture_output=True, text=True)
    if proc.returncode != 0:
        logger.warning("run_offer_eject: %s exited %s: %s", _OFFER_EJECT_SCRIPT, proc.returncode, proc.stderr.strip())


def _selection_labels(selection, catalog):
    """Group selected catalog entries' labels by group, for the manifest."""
    labels = {}
    for entry in catalog:
        if entry.index in selection.get(entry.group, set()):
            labels.setdefault(entry.group, []).append(entry.label)
    return labels


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _key_example_declaration_order(repo_root):
    """Ordered (not just set) variable names from keyExample.py, for stable output ordering."""
    import ast
    path = os.path.join(repo_root, "utilities", "keyExample.py")
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    order = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    order.append(target.id)
    return order


_JAMF_NAMES = frozenset({"jamfClientID", "jamfClientSecret", "jamfURL"})
_JAMF_CONFIRM_PHRASE = "INCLUDE JAMF"


# ---------------------------------------------------------------------------
# Tk UI -- not unit-tested, matches this codebase's convention
# ---------------------------------------------------------------------------

def open_partial_install_builder(parent, repo_root: str = None):
    """Open the partial-install checklist window.

    Args:
        parent: Tk parent widget.
        repo_root: Absolute path to the repository root; defaults to the
            directory two levels up from this file (utilities/../).
    """
    if repo_root is None:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    logger.debug("open_partial_install_builder: loading catalog")
    catalog = routingCatalog.load_catalog(repo_root)
    entries_by_group = {}
    for entry in catalog:
        entries_by_group.setdefault(entry.group, []).append(entry)

    win = tk.Toplevel(parent)
    win.title("Build Partial-Install USB")
    win.geometry("640x640")

    check_vars = {}  # (group, index) -> tk.BooleanVar
    consisterizer_selected = tk.BooleanVar(value=False)

    notebook = ttk.Notebook(win)
    notebook.pack(fill="both", expand=True, padx=10, pady=(10, 0))

    group_titles = {
        "asset": "Asset Functions",
        "other": "Other Functions",
        "consisterizer_submit": "Consisterizer Submit Scripts (requires Consisterizer)",
    }

    _debounce_id = {"id": None}

    def schedule_recompute():
        if _debounce_id["id"] is not None:
            win.after_cancel(_debounce_id["id"])
        _debounce_id["id"] = win.after(150, recompute_summary)

    submit_checkboxes = []

    def on_toggle(entry):
        if entry.group == "asset" and entry.label == "Consisterizer":
            consisterizer_selected.set(check_vars[(entry.group, entry.index)].get())
            _update_submit_scripts_enabled()
        schedule_recompute()

    def _update_submit_scripts_enabled():
        enabled = consisterizer_selected.get()
        for cb, var, entry in submit_checkboxes:
            cb.configure(state="normal" if enabled else "disabled")
            if not enabled and var.get():
                var.set(False)

    for group, entries in entries_by_group.items():
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=group_titles.get(group, group))
        for entry in entries:
            var = tk.BooleanVar(value=False)
            check_vars[(group, entry.index)] = var
            cb = tk.Checkbutton(frame, text=entry.label, variable=var,
                                 command=lambda e=entry: on_toggle(e))
            cb.pack(anchor="w", padx=10, pady=3)
            if group == "consisterizer_submit":
                cb.configure(state="disabled")
                submit_checkboxes.append((cb, var, entry))

    summary_frame = tk.Frame(win)
    summary_frame.pack(fill="x", padx=10, pady=10)
    summary_var = tk.StringVar(value="Nothing selected yet.")
    tk.Label(summary_frame, textvariable=summary_var, justify="left", anchor="w", wraplength=600).pack(fill="x")

    jamf_banner = tk.Label(
        win, text="⚠ This selection includes Jamf Pro credentials.",
        bg="#a3341c", fg="white", font=("", 12, "bold"), pady=6,
    )
    # Not packed until a recompute finds Jamf names in the derived set.

    def current_selection():
        sel = {}
        for (group, index), var in check_vars.items():
            if var.get():
                sel.setdefault(group, set()).add(index)
        return sel

    def recompute_summary():
        _debounce_id["id"] = None
        selection = current_selection()
        total_selected = sum(len(v) for v in selection.values())
        if total_selected == 0:
            summary_var.set("Nothing selected yet.")
            jamf_banner.pack_forget()
            return
        try:
            trace = compute_selection_trace(selection, catalog, repo_root)
        except (keyDependencyGraph.UnresolvedImportError, keyDependencyGraph.UnknownKeyNameError) as exc:
            summary_var.set(f"Could not compute dependencies: {exc}")
            jamf_banner.pack_forget()
            return
        names = ", ".join(sorted(trace.key_names))
        summary_var.set(f"{len(trace.files)} files · {len(trace.key_names)} secrets:\n{names}")
        if trace.key_names & _JAMF_NAMES:
            jamf_banner.pack(fill="x", padx=10, pady=(0, 10), before=summary_frame)
        else:
            jamf_banner.pack_forget()

    def confirm_jamf_inclusion() -> bool:
        prompt = tk.Toplevel(win)
        prompt.title("Confirm Jamf Credentials")
        prompt.grab_set()
        tk.Label(
            prompt,
            text=(
                "This install includes Jamf Pro credentials.\n\n"
                "Whoever receives this USB will be able to act on every enrolled\n"
                "device in Jamf -- not just the assets this tool normally touches.\n"
                "Unlike the other credentials this app manages, a leaked Jamf secret\n"
                "can't be meaningfully contained by rotating a Snipe-IT token; the\n"
                "blast radius is the whole fleet.\n\n"
                f"Type {_JAMF_CONFIRM_PHRASE!r} to confirm this is intentional."
            ),
            justify="left", wraplength=420, padx=16, pady=16,
        ).pack()
        entry_var = tk.StringVar()
        tk.Entry(prompt, textvariable=entry_var, width=30).pack(pady=(0, 12))
        result = {"confirmed": False}

        def on_ok():
            result["confirmed"] = entry_var.get().strip() == _JAMF_CONFIRM_PHRASE
            prompt.destroy()

        btn_frame = tk.Frame(prompt)
        btn_frame.pack(pady=(0, 16))
        tk.Button(btn_frame, text="Cancel", command=prompt.destroy).pack(side="left", padx=6)
        tk.Button(btn_frame, text="Confirm", command=on_ok).pack(side="left", padx=6)
        prompt.wait_window()
        return result["confirmed"]

    def _set_building(is_building, message=""):
        build_button.configure(state="disabled" if is_building else "normal")
        cancel_button.configure(state="disabled" if is_building else "normal")
        if message:
            summary_var.set(message)

    def _run_build_in_background(selection):
        """Disk select/erase, populate, finalize -- off the Tk thread.

        Erasing/formatting the USB alone can take the better part of a
        minute; running it via a blocking subprocess.run() on the Tk thread
        would freeze the whole window (and look hung) for that whole time.
        Every other slow external operation in this app (the updater,
        make_installer_usb.command's own launch) is fired off detached or
        threaded for the same reason -- this matches that.
        """
        try:
            logger.info("on_build: starting disk select/erase")
            usb_mount = run_select_and_erase(repo_root)
        except BuildCancelled:
            logger.info("on_build: disk selection cancelled by admin")
            win.after(0, lambda: _set_building(False, "Build cancelled."))
            return
        except RuntimeError as exc:
            # `except ... as exc` deletes `exc` from scope once this block
            # ends, and the lambda below isn't called until later (via
            # .after()) -- bind the message now via a default argument
            # rather than closing over a name that won't exist by then.
            logger.error("on_build: select_and_erase_usb.command failed: %s", exc)
            win.after(0, lambda msg=str(exc): _on_build_failed(msg))
            return
        logger.info("on_build: disk select/erase reported mount path=%s", usb_mount)

        try:
            summary = populate_usb(selection, repo_root, usb_mount)
            run_finalize(repo_root, usb_mount)
        except Exception as exc:
            logger.exception("on_build: failed while populating/finalizing USB")
            win.after(0, lambda msg=f"Failed while writing to the USB:\n\n{exc}": _on_build_failed(msg))
            return

        win.after(0, lambda: _on_build_succeeded(usb_mount, summary))

    def _on_build_failed(message):
        logger.error("on_build: build failed: %s", message)
        _set_building(False)
        messagebox.showerror("Build Partial-Install USB", message)
        recompute_summary()

    def _on_build_succeeded(usb_mount, summary):
        # Show the summary and let the admin actually go look at the drive
        # in Finder BEFORE anything offers to eject it -- offer_eject.command
        # is deliberately called after this dialog is dismissed, not before.
        messagebox.showinfo(
            "Build Partial-Install USB",
            f"USB ready at {usb_mount}.\n\n"
            f"{summary['file_count']} files, {len(summary['included_key_names'])} secrets included.\n"
            "Open the drive in Finder to check utilities/Key.py now if you want to -- "
            "the eject prompt comes next, after you close this.",
        )
        run_offer_eject(repo_root, usb_mount)
        win.destroy()

    def on_build():
        selection = current_selection()
        if sum(len(v) for v in selection.values()) == 0:
            messagebox.showerror("Build Partial-Install USB", "Select at least one function first.")
            return
        try:
            trace = compute_selection_trace(selection, catalog, repo_root)
        except (keyDependencyGraph.UnresolvedImportError, keyDependencyGraph.UnknownKeyNameError) as exc:
            messagebox.showerror("Build Partial-Install USB", f"Could not compute dependencies:\n\n{exc}")
            return

        if trace.key_names & _JAMF_NAMES:
            if not confirm_jamf_inclusion():
                logger.info("on_build: Jamf inclusion not confirmed, build cancelled")
                return

        _set_building(True, "Building... pick and erase the USB when prompted (this can take a minute).")
        threading.Thread(target=_run_build_in_background, args=(selection,), daemon=True).start()

    button_frame = tk.Frame(win)
    button_frame.pack(fill="x", padx=10, pady=(0, 10))
    build_button = tk.Button(button_frame, text="Build", command=on_build)
    build_button.pack(side="right")
    cancel_button = tk.Button(button_frame, text="Cancel", command=win.destroy)
    cancel_button.pack(side="right", padx=(0, 8))

    return win
