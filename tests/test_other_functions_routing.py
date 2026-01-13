"""Tests for non-asset routing table integrity."""

from otherManagementFunctions import otherFunctionsRouting as routing


def test_other_functions_routing_alignment():
    assert len(routing.other_func_list) == len(routing.other_func_listTXT)
    assert all(callable(fn) for fn in routing.other_func_list)
    assert all(isinstance(label, str) and label.strip() for label in routing.other_func_listTXT)
