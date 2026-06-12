import pytest
from rca_kg.class_map import UnknownEquipmentClass, iso_to_kg_map, resolve_equipment_class


def test_map_has_centrifugal_pump():
    m = iso_to_kg_map()
    assert m["pump.centrifugal"] == "equipment-class:bb1"
    assert m["pump"] == "equipment-class:pump"


def test_resolve_known():
    assert resolve_equipment_class("pump.centrifugal") == "equipment-class:bb1"


def test_resolve_unknown_raises():
    with pytest.raises(UnknownEquipmentClass):
        resolve_equipment_class("compressor.reciprocating")


def test_every_value_is_a_seeded_node_id():
    assert all(v.startswith("equipment-class:") for v in iso_to_kg_map().values())
