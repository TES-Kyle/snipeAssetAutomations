"""Tests for battery EA map collection."""

from otherManagementFunctions import batteryDataSync as bds


class DummyHW:
    def __init__(self, extensionAttributes=None):
        self.extensionAttributes = extensionAttributes


class DummyComp:
    def __init__(self, extensionAttributes=None, hardware=None):
        self.extensionAttributes = extensionAttributes
        self.hardware = hardware


def test_collect_ea_map_merges_sources():
    comp = DummyComp(
        extensionAttributes=[{"name": "Battery Design Capacity", "value": {"displayValue": "5000"}}],
        hardware=DummyHW(
            extensionAttributes=[{"name": "Battery Maximum Capacity", "value": "4500"}]
        ),
    )

    ea_map = bds._collect_ea_map(comp, debug_label="test")

    assert ea_map["battery design capacity"] == "5000"
    assert ea_map["battery maximum capacity"] == "4500"


def test_collect_ea_map_uses_dict_extension_attributes():
    comp = DummyComp(extensionAttributes=None, hardware=None)
    comp.__dict__["extensionAttributes"] = [{"name": "batteryCondition", "value": "Normal"}]

    ea_map = bds._collect_ea_map(comp, debug_label="test")

    assert ea_map["batterycondition"] == "Normal"
