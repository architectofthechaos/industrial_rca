// 0001_initial — uniqueness constraints on id for every KG label, plus code indexes
// on the two lookup-heavy ontology labels (Sprint 2a Task 3).

CREATE CONSTRAINT equipment_class_id IF NOT EXISTS FOR (n:EquipmentClass) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT failure_mode_id IF NOT EXISTS FOR (n:FailureMode) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT failure_mechanism_id IF NOT EXISTS FOR (n:FailureMechanism) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT maintenance_activity_id IF NOT EXISTS FOR (n:MaintenanceActivity) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT subunit_id IF NOT EXISTS FOR (n:Subunit) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT component_id IF NOT EXISTS FOR (n:Component) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT site_id IF NOT EXISTS FOR (n:Site) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT area_id IF NOT EXISTS FOR (n:Area) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT unit_id IF NOT EXISTS FOR (n:Unit) REQUIRE n.id IS UNIQUE;

CREATE INDEX equipment_class_code IF NOT EXISTS FOR (n:EquipmentClass) ON (n.code);
CREATE INDEX failure_mode_code IF NOT EXISTS FOR (n:FailureMode) ON (n.code);
