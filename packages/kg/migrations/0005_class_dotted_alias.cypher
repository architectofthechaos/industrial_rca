// 0005 — backfill the dotted ISO alias on EquipmentClass nodes (D1).
MATCH (n:EquipmentClass {id: "equipment-class:pump"}) SET n.dotted = "pump";
MATCH (n:EquipmentClass {id: "equipment-class:bb1"})  SET n.dotted = "pump.centrifugal";
