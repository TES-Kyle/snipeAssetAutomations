"""Tests for asset routing table integrity."""

from assetManagementFunctions import assetFunctionsRouting as routing


def test_asset_functions_routing_alignment():
    assert len(routing.func_list) == len(routing.func_listTXT)
    assert all(callable(fn) for fn in routing.func_list)
    assert all(isinstance(label, str) and label.strip() for label in routing.func_listTXT)
