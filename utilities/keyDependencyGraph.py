"""Static dependency tracer for utilities/Key.py secrets.

Given a routing entry's source file, walks its real (now-explicit, since
the wildcard-import cleanup) local imports to find every Key.py credential
that entry's code can actually reach -- so a partial-install USB can ship
only the secrets a chosen set of GUI functions needs, without a manually
maintained (and therefore driftable) mapping.

AST-based, not text-search-based: a plain grep for a module name matches
docstrings and comments as readily as real imports (utilities/api_retry.py
mentions utilities.jamfPrestageCommon in a comment despite never importing
it), which would poison the graph. Only real ast.Import/ast.ImportFrom and
ast.Attribute/getattr() nodes count here.

Local package resolution is filesystem-based (does <repo_root>/<first
dotted component> exist as a directory?) rather than a hardcoded list of
package names, so it doesn't need updating if a new top-level package is
added later.
"""

import ast
import logging
import os

logger = logging.getLogger(__name__)

# Files every install needs regardless of which routing entries are
# selected: otherApiBits.py (every Snipe-IT call) and api_user.py (the
# credential picker), both imported by virtually every feature module.
# Traced the same way as any selected entry -- not a hardcoded secret list
# -- so this can't silently drift out of sync with what those files
# actually reference. See tests/test_keyDependencyGraph.py.
BASELINE_INFRA_FILES = ("utilities/otherApiBits.py", "utilities/api_user.py")


class UnresolvedImportError(Exception):
    """A local-looking import couldn't be resolved to an actual file.

    Raised rather than silently skipped -- for a partial-install build,
    guessing wrong about what a module depends on is worse than refusing
    to build at all.
    """


class UnknownKeyNameError(Exception):
    """Code references a utilities.Key attribute that keyExample.py doesn't list.

    Almost certainly a typo or a Key.py addition that keyExample.py (the
    documented, canonical variable list per utilities/__init__.py) hasn't
    caught up with yet -- either way, worth stopping on rather than
    quietly ignoring or quietly including everything to be safe.
    """


class ModuleTrace:
    """Result of tracing one or more entry points: files touched + Key.py names needed."""

    __slots__ = ("files", "key_names")

    def __init__(self, files, key_names):
        self.files = frozenset(files)
        self.key_names = frozenset(key_names)

    def __eq__(self, other):
        if not isinstance(other, ModuleTrace):
            return NotImplemented
        return self.files == other.files and self.key_names == other.key_names

    def __repr__(self):
        return f"ModuleTrace(files={sorted(self.files)!r}, key_names={sorted(self.key_names)!r})"

    def union(self, other):
        """Return a new ModuleTrace combining this one with another."""
        return ModuleTrace(self.files | other.files, self.key_names | other.key_names)


def load_known_key_names(repo_root: str) -> frozenset:
    """Return the set of variable names keyExample.py declares.

    Mirrors utilities/__init__.py's own treatment of keyExample.py as the
    canonical source of truth for what a Key.py may contain.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        Frozenset of non-private top-level assignment target names.
    """
    path = os.path.join(repo_root, "utilities", "keyExample.py")
    tree = ast.parse(_read(path), filename=path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
    logger.debug("load_known_key_names: %s names from keyExample.py", len(names))
    return frozenset(names)


def trace_module(entry_rel_path: str, repo_root: str, known_key_names: frozenset = None) -> ModuleTrace:
    """Trace one entry point's transitive local-import closure.

    Args:
        entry_rel_path: Path to the entry file, relative to repo_root
            (e.g. "assetManagementFunctions/checkIn.py"), forward-slashed.
        repo_root: Absolute path to the repository root.
        known_key_names: Result of load_known_key_names(repo_root); loaded
            automatically if not supplied (callers tracing many entries in
            one build should load it once and pass it in).

    Returns:
        ModuleTrace of every local file reached and every Key.py name
        referenced by code in that closure.

    Raises:
        UnresolvedImportError: A local-looking import couldn't be resolved.
        UnknownKeyNameError: Code references a Key.py name keyExample.py
            doesn't list.
    """
    if known_key_names is None:
        known_key_names = load_known_key_names(repo_root)

    seen_files = set()
    key_names = set()
    queue = [_norm(entry_rel_path)]

    while queue:
        rel_path = queue.pop()
        if rel_path in seen_files:
            continue
        seen_files.add(rel_path)

        abs_path = os.path.join(repo_root, *rel_path.split("/"))
        tree = ast.parse(_read(abs_path), filename=abs_path)

        key_aliases = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                _handle_import_from(node, rel_path, repo_root, queue, key_names, key_aliases, known_key_names)
            elif isinstance(node, ast.Import):
                _handle_import(node, rel_path, repo_root, queue, known_key_names)

        if key_aliases:
            _scan_key_attribute_accesses(tree, key_aliases, rel_path, key_names, known_key_names)

    logger.info("trace_module: entry=%s -> %s files, %s key names", entry_rel_path, len(seen_files), len(key_names))
    return ModuleTrace(seen_files, key_names)


def trace_selection(entry_rel_paths, repo_root: str) -> ModuleTrace:
    """Trace a set of selected routing entries plus the always-included baseline.

    Args:
        entry_rel_paths: Iterable of entry file paths relative to repo_root.
        repo_root: Absolute path to the repository root.

    Returns:
        Union ModuleTrace across every selected entry and BASELINE_INFRA_FILES.
    """
    known_key_names = load_known_key_names(repo_root)
    result = ModuleTrace(set(), set())
    for rel_path in (*entry_rel_paths, *BASELINE_INFRA_FILES):
        result = result.union(trace_module(rel_path, repo_root, known_key_names))
    return result


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _read(abs_path):
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()


def _norm(rel_path):
    return rel_path.replace(os.sep, "/")


def resolve_local_module(module_dotted, repo_root):
    """Return the repo-relative file path for a dotted module path, or None."""
    if not module_dotted:
        return None
    parts = module_dotted.split(".")
    candidate = os.path.join(repo_root, *parts) + ".py"
    if os.path.isfile(candidate):
        return _norm(os.path.join(*parts) + ".py")
    pkg_init = os.path.join(repo_root, *parts, "__init__.py")
    if os.path.isfile(pkg_init):
        return _norm(os.path.join(*parts, "__init__.py"))
    return None


def first_component_is_local(module_dotted, repo_root):
    first = module_dotted.split(".", 1)[0]
    return bool(first) and os.path.isdir(os.path.join(repo_root, first))


def _dotted_for_importfrom(node, current_rel_path, repo_root):
    """Return the absolute dotted module path an ImportFrom node refers to."""
    if not node.level:
        return node.module or ""
    # Relative import: walk up `level` package directories from the
    # importing file's own location. Not used anywhere in this codebase
    # today (every import here is absolute), but handled for correctness.
    dir_parts = current_rel_path.split("/")[:-1]
    up = node.level - 1
    if up:
        dir_parts = dir_parts[:-up] if up <= len(dir_parts) else []
    base = ".".join(dir_parts)
    if node.module:
        return f"{base}.{node.module}" if base else node.module
    return base


def _handle_import_from(node, current_rel_path, repo_root, queue, key_names, key_aliases, known_key_names):
    module_dotted = _dotted_for_importfrom(node, current_rel_path, repo_root)

    if module_dotted == "utilities.Key":
        for alias in node.names:
            _add_key_name(alias.name, current_rel_path, key_names, known_key_names)
        return

    for alias in node.names:
        if module_dotted == "utilities" and alias.name == "Key":
            key_aliases.add(alias.asname or alias.name)
            continue

        sub_dotted = f"{module_dotted}.{alias.name}" if module_dotted else alias.name
        resolved = resolve_local_module(sub_dotted, repo_root)
        if resolved:
            queue.append(resolved)
            continue

        # A single-component module (e.g. "from utilities import X") that
        # doesn't resolve as a submodule might legitimately be a plain
        # attribute on that package's __init__.py -- not an error.
        if "." not in module_dotted:
            if first_component_is_local(sub_dotted, repo_root):
                continue
            # Not local at all (stdlib/third-party) -- ignore.
            continue

        # A fully dotted module path (from a.b.c import name) that fails to
        # resolve either as a.b.c/name.py or as a.b.c.py should always have
        # resolved if the code actually runs -- refuse to guess.
        if first_component_is_local(module_dotted, repo_root):
            resolved_module = resolve_local_module(module_dotted, repo_root)
            if resolved_module:
                queue.append(resolved_module)
            else:
                raise UnresolvedImportError(
                    f"{current_rel_path}: cannot resolve local import "
                    f"'from {module_dotted} import {alias.name}'"
                )


def _handle_import(node, current_rel_path, repo_root, queue, known_key_names):
    for alias in node.names:
        dotted = alias.name
        if dotted == "utilities.Key" or dotted.startswith("utilities.Key."):
            raise UnresolvedImportError(
                f"{current_rel_path}: 'import {dotted}' is not supported for Key -- "
                "rewrite as 'from utilities import Key' or 'from utilities.Key import name'."
            )
        resolved = resolve_local_module(dotted, repo_root)
        if resolved:
            queue.append(resolved)
        elif first_component_is_local(dotted, repo_root):
            raise UnresolvedImportError(f"{current_rel_path}: cannot resolve local import 'import {dotted}'")
        # else: stdlib/third-party -- ignore.


def _add_key_name(name, current_rel_path, key_names, known_key_names):
    if name not in known_key_names:
        raise UnknownKeyNameError(
            f"{current_rel_path}: references Key.{name}, which isn't declared in utilities/keyExample.py"
        )
    key_names.add(name)


def _scan_key_attribute_accesses(tree, key_aliases, current_rel_path, key_names, known_key_names):
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in key_aliases:
            _add_key_name(node.attr, current_rel_path, key_names, known_key_names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id in key_aliases:
                lit = node.args[1]
                if isinstance(lit, ast.Constant) and isinstance(lit.value, str):
                    _add_key_name(lit.value, current_rel_path, key_names, known_key_names)
