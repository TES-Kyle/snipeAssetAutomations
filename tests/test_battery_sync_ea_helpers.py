"""Tests for battery EA helper functions."""

from otherManagementFunctions import batteryDataSync as bds


class Dummy:
    def __init__(self, name=None, value=None):
        self.name = name
        self.value = value


def test_ea_name_from_obj():
    ea = Dummy(name="Battery Design Capacity")
    assert bds._ea_name(ea) == "Battery Design Capacity"


def test_ea_value_from_dict():
    ea = {"value": {"displayValue": "4567"}}
    assert bds._ea_value(ea) == "4567"


def test_ea_value_from_obj_value():
    ea = Dummy(value={"value": "1234"})
    assert bds._ea_value(ea) == "1234"


def test_ea_value_from_values_list():
    ea = {"values": ["", None, "555"]}
    assert bds._ea_value(ea) == "555"


def test_ea_value_from_value_object_fallback():
    class Holder:
        def __init__(self):
            self.value = type("V", (), {"values": ["", "777"]})()
    ea = Holder()
    assert bds._ea_value(ea) is ea.value
