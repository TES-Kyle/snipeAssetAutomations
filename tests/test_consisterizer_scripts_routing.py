"""Tests for Consisterizer submit scripts routing table."""

from consisterizer import consisterizerScriptsRouting as routing


def test_consisterizer_scripts_routing_alignment():
    assert len(routing.submit_func_list) == len(routing.submit_func_listTXT)
    assert all(callable(fn) for fn in routing.submit_func_list)
    assert all(isinstance(label, str) and label.strip() for label in routing.submit_func_listTXT)
