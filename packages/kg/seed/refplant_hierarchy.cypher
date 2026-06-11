// Reference-plant hierarchy seed (Refinery GC) — Sprint 2a Task 4.
// Idempotent: nodes MERGEd on id, CONTAINS edges MERGEd after MATCH. Safe to re-run.
// Ids mint segments with rca_kg.slugs.slug ("UNIT-101" -> "unit-101").

MERGE (n:Site {id: "site:refinery-gc"}) SET n.name = "Refinery GC", n.plant_id = "refinery-gc";

MERGE (n:Area {id: "area:refinery-gc:area-100"}) SET n.name = "AREA-100", n.plant_id = "refinery-gc";
MERGE (n:Area {id: "area:refinery-gc:area-200"}) SET n.name = "AREA-200", n.plant_id = "refinery-gc";

MERGE (n:Unit {id: "unit:refinery-gc:unit-101"}) SET n.name = "UNIT-101", n.plant_id = "refinery-gc";
MERGE (n:Unit {id: "unit:refinery-gc:unit-102"}) SET n.name = "UNIT-102", n.plant_id = "refinery-gc";
MERGE (n:Unit {id: "unit:refinery-gc:unit-201"}) SET n.name = "UNIT-201", n.plant_id = "refinery-gc";

MATCH (s:Site {id: "site:refinery-gc"})
UNWIND ["area:refinery-gc:area-100", "area:refinery-gc:area-200"] AS area_id
MATCH (a:Area {id: area_id})
MERGE (s)-[:CONTAINS]->(a);

MATCH (a:Area {id: "area:refinery-gc:area-100"})
UNWIND ["unit:refinery-gc:unit-101", "unit:refinery-gc:unit-102"] AS unit_id
MATCH (u:Unit {id: unit_id})
MERGE (a)-[:CONTAINS]->(u);

MATCH (a:Area {id: "area:refinery-gc:area-200"})
UNWIND ["unit:refinery-gc:unit-201"] AS unit_id
MATCH (u:Unit {id: unit_id})
MERGE (a)-[:CONTAINS]->(u);
