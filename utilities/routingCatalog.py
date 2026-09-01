"""Catalog of every selectable partial-install entry across all three routing tables.

Three files define "what's a selectable feature" in this app:
  - assetManagementFunctions/assetFunctionsRouting.py (func_list/func_listTXT)
  - otherManagementFunctions/otherFunctionsRouting.py (other_func_list/other_func_listTXT)
  - consisterizer/consisterizerScriptsRouting.py (submit_func_list/submit_func_listTXT)

The third one isn't a top-level GUI button -- it's the "run this after
saving" checkbox list inside the Consisterizer window -- but it's exactly
as independently selectable as the other two (one of its two entries is
"Remove PreStage and Delete in Jamf", discovered via keyDependencyGraph
tracing straight through consisterizer.py). It's marked as requiring
Consisterizer's own top-level entry, since a submit-script that only runs
from inside that window is meaningless without it.

Entries are matched to their traceable source file(s) statically, by
reading each routing file's own import statements -- never by importing
the routing files themselves (that would require live Snipe-IT/Jamf
credentials just to build a catalog). A list element can reference more
than one imported name (e.g. "Bulk Check-in" is
`lambda x: consisterizer(x, alias=bulkCheckIn)`, touching both
consisterizer.py and aliases.py), so each entry's defining_files is a set,
not a single path.
"""

import ast
import logging
from dataclasses import dataclass

from utilities.keyDependencyGraph import resolve_local_module

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingFileSpec:
    """Static description of one routing table file."""

    rel_path: str
    list_var: str
    labels_var: str
    group: str
    requires_label: str = None  # label (in another group) that must also be selected


ROUTING_SPECS = (
    RoutingFileSpec(
        rel_path="assetManagementFunctions/assetFunctionsRouting.py",
        list_var="func_list",
        labels_var="func_listTXT",
        group="asset",
    ),
    RoutingFileSpec(
        rel_path="otherManagementFunctions/otherFunctionsRouting.py",
        list_var="other_func_list",
        labels_var="other_func_listTXT",
        group="other",
    ),
    RoutingFileSpec(
        rel_path="consisterizer/consisterizerScriptsRouting.py",
        list_var="submit_func_list",
        labels_var="submit_func_listTXT",
        group="consisterizer_submit",
        requires_label="Consisterizer",
    ),
)


@dataclass(frozen=True)
class RoutingEntry:
    """One selectable item: a button, or a Consisterizer submit-script checkbox."""

    label: str
    group: str
    index: int  # position within its own routing file's list -- stable id for rewriting
    source_spec: RoutingFileSpec
    defining_files: frozenset  # repo-relative paths, traceable via keyDependencyGraph


class RoutingFileParseError(Exception):
    """A routing file doesn't match the expected `list_var = [...]` / `labels_var = [...]` shape."""


def load_catalog(repo_root: str) -> list:
    """Parse all three routing files into a flat list of RoutingEntry.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        List of RoutingEntry, in routing-file then list-index order.
    """
    catalog = []
    for spec in ROUTING_SPECS:
        catalog.extend(_load_entries_for_spec(spec, repo_root))
    logger.info("load_catalog: %s selectable entries across %s routing files", len(catalog), len(ROUTING_SPECS))
    return catalog


def render_trimmed_routing_file(repo_root: str, spec: RoutingFileSpec, selected_indices) -> str:
    """Return new source text for spec's routing file, keeping only selected_indices.

    Preserves the file's docstring/header, only the import statements whose
    names are still referenced by a kept entry, and the original source
    text of each kept list/label element (via ast.get_source_segment) --
    so formatting for what's kept is untouched, not reconstructed.

    Args:
        repo_root: Absolute path to the repository root.
        spec: Which routing file to rewrite.
        selected_indices: Iterable of list-index positions to keep.

    Returns:
        Full new source text for the trimmed routing file.
    """
    selected_indices = set(selected_indices)
    abs_path = _abs(repo_root, spec.rel_path)
    source = _read(abs_path)
    tree = ast.parse(source, filename=abs_path)

    import_nodes = _module_level_import_nodes(tree)
    list_assign, labels_assign = _find_list_and_labels_assigns(tree, spec, abs_path)
    list_elts = list_assign.value.elts
    label_elts = labels_assign.value.elts

    kept_names = set()
    for i in selected_indices:
        kept_names |= _referenced_names(list_elts[i])

    kept_import_lines = []
    for node in import_nodes:
        node_names = {a.asname or a.name for a in node.names}
        if node_names & kept_names:
            kept_import_lines.append(ast.get_source_segment(source, node))

    list_items = ",\n    ".join(
        ast.get_source_segment(source, list_elts[i]) for i in sorted(selected_indices)
    )
    label_items = ",\n    ".join(
        ast.get_source_segment(source, label_elts[i]) for i in sorted(selected_indices)
    )

    docstring = ast.get_docstring(tree, clean=False)
    header = f'"""{docstring}"""\n\n' if docstring is not None else ""

    list_block = f"{spec.list_var} = [\n    {list_items}\n]\n" if list_items else f"{spec.list_var} = []\n"
    label_block = f"{spec.labels_var} = [\n    {label_items}\n]\n" if label_items else f"{spec.labels_var} = []\n"

    rendered = (
        f"{header}"
        f"import logging\n\n"
        f"logger = logging.getLogger(__name__)\n\n"
        + ("\n".join(kept_import_lines) + "\n\n" if kept_import_lines else "")
        + list_block
        + f'logger.info("{spec.rel_path.rsplit("/", 1)[-1][:-3]}: %s functions registered", len({spec.list_var}))\n\n'
        + label_block
    )
    return rendered


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _read(abs_path):
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()


def _abs(repo_root, rel_path):
    import os
    return os.path.join(repo_root, *rel_path.split("/"))


def _module_level_import_nodes(tree):
    return [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]


def _imported_name_map(tree, repo_root):
    """Map each name importable at module level to its resolved local file (if local)."""
    name_to_file = {}
    for node in _module_level_import_nodes(tree):
        if isinstance(node, ast.ImportFrom) and not node.level:
            module_dotted = node.module or ""
            for alias in node.names:
                local_name = alias.asname or alias.name
                # Two possible shapes: `from pkg.module import name` (name is
                # defined inside pkg/module.py -- try that combined path
                # first) or `from pkg import submodule` (submodule is its
                # own file, pkg/submodule.py -- the fallback).
                sub_dotted = f"{module_dotted}.{alias.name}" if module_dotted else alias.name
                resolved = resolve_local_module(sub_dotted, repo_root) or resolve_local_module(module_dotted, repo_root)
                if resolved:
                    name_to_file[local_name] = resolved
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = (alias.asname or alias.name).split(".")[0]
                resolved = resolve_local_module(alias.name, repo_root)
                if resolved:
                    name_to_file[local_name] = resolved
    return name_to_file


def _referenced_names(elt_node):
    """Every Name id referenced (read) within one list element's subtree."""
    return {n.id for n in ast.walk(elt_node) if isinstance(n, ast.Name)}


def _find_list_and_labels_assigns(tree, spec, abs_path):
    list_assign = labels_assign = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == spec.list_var:
                list_assign = node
            elif name == spec.labels_var:
                labels_assign = node
    if list_assign is None or not isinstance(list_assign.value, ast.List):
        raise RoutingFileParseError(f"{abs_path}: could not find `{spec.list_var} = [...]`")
    if labels_assign is None or not isinstance(labels_assign.value, ast.List):
        raise RoutingFileParseError(f"{abs_path}: could not find `{spec.labels_var} = [...]`")
    if len(list_assign.value.elts) != len(labels_assign.value.elts):
        raise RoutingFileParseError(
            f"{abs_path}: {spec.list_var} has {len(list_assign.value.elts)} entries but "
            f"{spec.labels_var} has {len(labels_assign.value.elts)}"
        )
    return list_assign, labels_assign


def _load_entries_for_spec(spec, repo_root):
    abs_path = _abs(repo_root, spec.rel_path)
    tree = ast.parse(_read(abs_path), filename=abs_path)
    list_assign, labels_assign = _find_list_and_labels_assigns(tree, spec, abs_path)
    name_to_file = _imported_name_map(tree, repo_root)

    entries = []
    for i, (elt, label_node) in enumerate(zip(list_assign.value.elts, labels_assign.value.elts)):
        if not isinstance(label_node, ast.Constant) or not isinstance(label_node.value, str):
            raise RoutingFileParseError(f"{abs_path}: {spec.labels_var}[{i}] is not a plain string literal")
        referenced = _referenced_names(elt)
        defining_files = frozenset(name_to_file[n] for n in referenced if n in name_to_file)
        if not defining_files:
            raise RoutingFileParseError(
                f"{abs_path}: {spec.list_var}[{i}] ({label_node.value!r}) doesn't resolve to any "
                "local source file -- can't be traced for Key.py dependencies"
            )
        entries.append(RoutingEntry(label_node.value, spec.group, i, spec, defining_files))
    return entries
