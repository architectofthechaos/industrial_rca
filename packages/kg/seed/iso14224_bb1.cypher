// ISO 14224 BB1 (centrifugal pump) ontology seed — Sprint 2a Task 4.
// Idempotent: nodes are MERGEd on id, edges MERGEd after MATCH. Safe to re-run.
// References: ISO 14224 Table B.3 (failure modes), B.4 (mechanisms), B.6 (activities).

// ---- EquipmentClass taxonomy ------------------------------------------------
MERGE (n:EquipmentClass {id: "equipment-class:rotating-equipment"}) SET n.name = "Rotating equipment", n.description = "Equipment category: machines with rotating parts.";
MERGE (n:EquipmentClass {id: "equipment-class:pump"}) SET n.code = "PU", n.name = "Pump", n.description = "Equipment class pumps (ISO 14224 A.2.2).", n.dotted = "pump";
MERGE (n:EquipmentClass {id: "equipment-class:bb1"}) SET n.code = "BB1", n.name = "Centrifugal pump", n.description = "Centrifugal pump equipment type (API 610 BB1 between-bearings style).", n.dotted = "pump.centrifugal";
MATCH (a:EquipmentClass {id: "equipment-class:rotating-equipment"})
UNWIND ["equipment-class:pump"] AS dst_id
MATCH (b:EquipmentClass {id: dst_id})
MERGE (a)-[:HAS_SUBCLASS]->(b);
MATCH (a:EquipmentClass {id: "equipment-class:pump"})
UNWIND ["equipment-class:bb1"] AS dst_id
MATCH (b:EquipmentClass {id: dst_id})
MERGE (a)-[:HAS_SUBCLASS]->(b);

// ---- FailureMode (ISO 14224 Table B.3) --------------------------------------
MERGE (n:FailureMode {id: "failure-mode:brd"}) SET n.code = "BRD", n.name = "Breakdown", n.description = "Serious damage; the pump is unable to operate.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:ero"}) SET n.code = "ERO", n.name = "Erratic output", n.description = "Output is oscillating, hunting or otherwise unstable.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:hio"}) SET n.code = "HIO", n.name = "High output", n.description = "Delivered flow or head above acceptance limits.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:loo"}) SET n.code = "LOO", n.name = "Low output", n.description = "Delivered flow or head below acceptance limits.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:vib"}) SET n.code = "VIB", n.name = "Vibration", n.description = "Abnormal vibration of the pump unit.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:lbp"}) SET n.code = "LBP", n.name = "Leakage process medium (internal)", n.description = "Process medium leaking internally past barriers within the pump.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:lcp"}) SET n.code = "LCP", n.name = "Leakage utility medium (internal)", n.description = "Utility medium (cooling, barrier fluid) leaking internally within the pump.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:std"}) SET n.code = "STD", n.name = "Structural deficiency", n.description = "Damage or deficiency of structural parts such as casing or supports.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:ohe"}) SET n.code = "OHE", n.name = "Overheating", n.description = "Machine parts running above design temperature.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:elp"}) SET n.code = "ELP", n.name = "External leakage process medium", n.description = "Process medium leaking from the pump to the environment.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:elu"}) SET n.code = "ELU", n.name = "External leakage utility medium", n.description = "Utility medium (lube oil, cooling water) leaking to the environment.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:fof"}) SET n.code = "FOF", n.name = "Failure to function on demand", n.description = "Pump does not start or deliver when demanded.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:inl"}) SET n.code = "INL", n.name = "Internal leakage", n.description = "Internal recirculation or leakage degrading hydraulic performance.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:noi"}) SET n.code = "NOI", n.name = "Noise", n.description = "Abnormal noise from the pump unit.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:oth"}) SET n.code = "OTH", n.name = "Other", n.description = "Failure modes not covered by the other categories.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:pde"}) SET n.code = "PDE", n.name = "Parameter deviation", n.description = "Monitored parameter (pressure, temperature, flow) outside limits.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:plu"}) SET n.code = "PLU", n.name = "Plugged/choked", n.description = "Flow restricted by full or partial blockage.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:ser"}) SET n.code = "SER", n.name = "Minor in-service problems", n.description = "Minor problems needing attention but not affecting the main function.", n.iso14224_ref = "B.3";
MERGE (n:FailureMode {id: "failure-mode:unk"}) SET n.code = "UNK", n.name = "Unknown", n.description = "Too little information to define a failure mode.", n.iso14224_ref = "B.3";

// ---- FailureMechanism (ISO 14224 Table B.4) ---------------------------------
MERGE (n:FailureMechanism {id: "failure-mechanism:other"}) SET n.name = "Other", n.description = "Other/unspecified failure mechanism (ISO 14224 B.4 'Other'); generic fallback when a mechanism cannot be resolved to a specific ontology node.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:mechanical-failure"}) SET n.name = "Mechanical failure", n.description = "General mechanical failure of moving parts.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:leakage"}) SET n.name = "Leakage", n.description = "Loss of fluid past a sealing surface or joint.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:vibration"}) SET n.name = "Vibration", n.description = "Excessive dynamic motion damaging parts over time.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:clearance-alignment-failure"}) SET n.name = "Clearance/alignment failure", n.description = "Wrong running clearances or alignment between parts.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:deformation"}) SET n.name = "Deformation", n.description = "Bending, buckling or other permanent distortion.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:looseness"}) SET n.name = "Looseness", n.description = "Loosening of bolted or fitted connections.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:sticking"}) SET n.name = "Sticking", n.description = "Seizure or jamming of parts meant to move.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:material-failure"}) SET n.name = "Material failure", n.description = "Degradation or defect of the base material.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:cavitation"}) SET n.name = "Cavitation", n.description = "Vapour bubble collapse eroding hydraulic surfaces.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:corrosion"}) SET n.name = "Corrosion", n.description = "Electrochemical attack of wetted or exposed surfaces.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:erosion"}) SET n.name = "Erosion", n.description = "Material removal by abrasive or high-velocity flow.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:wear"}) SET n.name = "Wear", n.description = "Gradual material loss between rubbing surfaces.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:breakage"}) SET n.name = "Breakage", n.description = "Fracture of a load-carrying part.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:fatigue"}) SET n.name = "Fatigue", n.description = "Crack initiation and growth under cyclic load.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:overheating"}) SET n.name = "Overheating", n.description = "Heat input above design limits damaging parts.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:burst"}) SET n.name = "Burst", n.description = "Sudden rupture from overpressure.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:instrument-failure"}) SET n.name = "Instrument failure", n.description = "Failure of a measuring instrument.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:control-failure"}) SET n.name = "Control failure", n.description = "Failure of regulation or control function.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:no-signal"}) SET n.name = "No signal/indication/alarm", n.description = "Expected signal, indication or alarm absent.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:faulty-signal"}) SET n.name = "Faulty signal/indication/alarm", n.description = "Signal, indication or alarm wrong or spurious.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:software-failure"}) SET n.name = "Software failure", n.description = "Faulty or hung control software.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:electrical-failure"}) SET n.name = "Electrical failure", n.description = "General electrical failure.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:short-circuit"}) SET n.name = "Short circuit", n.description = "Unintended low-resistance electrical path.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:open-circuit"}) SET n.name = "Open circuit", n.description = "Broken electrical continuity.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:no-power"}) SET n.name = "No power/voltage", n.description = "Missing or insufficient electrical supply.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:faulty-power"}) SET n.name = "Faulty power/voltage", n.description = "Wrong or unstable electrical supply.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:earth-fault"}) SET n.name = "Earth/isolation fault", n.description = "Insulation breakdown to earth.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:external-influence"}) SET n.name = "External influence", n.description = "Damage from outside the boundary: impact, environment, foreign objects.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:blockage"}) SET n.name = "Blockage/plugged", n.description = "Flow path restricted by debris or deposits.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:contamination"}) SET n.name = "Contamination", n.description = "Foreign matter in process or utility fluids.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:misalignment"}) SET n.name = "Misalignment", n.description = "Shaft or coupling alignment outside tolerance.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:imbalance"}) SET n.name = "Imbalance", n.description = "Rotating mass unbalance causing vibration.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:bearing-wear"}) SET n.name = "Bearing wear", n.description = "Degradation of rolling or sliding bearings.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:seal-failure"}) SET n.name = "Seal failure", n.description = "Loss of sealing capability of shaft or static seals.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:lubrication-failure"}) SET n.name = "Lubrication failure", n.description = "Loss, degradation or contamination of lubricant supply.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:fouling"}) SET n.name = "Fouling", n.description = "Deposits building up on heat-transfer or flow surfaces.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:overload"}) SET n.name = "Overload", n.description = "Operation beyond rated load, torque or duty.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:cracking"}) SET n.name = "Cracking", n.description = "Crack formation in pressure-containing or structural parts.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:loose-connection"}) SET n.name = "Loose connection", n.description = "Loose electrical or instrument connection causing intermittent faults.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:calibration-drift"}) SET n.name = "Calibration drift", n.description = "Gradual loss of instrument measurement accuracy.", n.iso14224_ref = "B.4";
MERGE (n:FailureMechanism {id: "failure-mechanism:ageing"}) SET n.name = "Ageing", n.description = "Time-dependent degradation of elastomers, gaskets and soft parts.", n.iso14224_ref = "B.4";

// ---- MaintenanceActivity (ISO 14224 Table B.6) ------------------------------
MERGE (n:MaintenanceActivity {id: "maintenance-activity:replace"}) SET n.name = "Replace", n.description = "Replacement of the item by a new or refurbished one.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:repair"}) SET n.name = "Repair", n.description = "Manual maintenance action to restore an item to its original state.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:modify"}) SET n.name = "Modify", n.description = "Replace, renew or change the item or a part of it with something different.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:adjust"}) SET n.name = "Adjust", n.description = "Bringing any out-of-tolerance condition into tolerance.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:refit"}) SET n.name = "Refit", n.description = "Minor repair/servicing activity to bring back an item to an acceptable state.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:check"}) SET n.name = "Check", n.description = "Cause of failure investigated without repair or with minor restoring actions.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:service"}) SET n.name = "Service", n.description = "Periodic service tasks: cleaning, replenishment of consumables.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:test"}) SET n.name = "Test", n.description = "Periodic test of function or performance.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:inspect"}) SET n.name = "Inspect", n.description = "Periodic inspection: careful scrutiny carried out with or without dismantling.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:overhaul"}) SET n.name = "Overhaul", n.description = "Major overhaul: comprehensive inspection and restoration.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:lubricate"}) SET n.name = "Lubricate", n.description = "Lubrication of the item.", n.iso14224_ref = "B.6";
MERGE (n:MaintenanceActivity {id: "maintenance-activity:clean"}) SET n.name = "Clean", n.description = "Machine cleaning of the item.", n.iso14224_ref = "B.6";

// ---- Subunit (BB1 boundary subdivision) -------------------------------------
MERGE (n:Subunit {id: "subunit:power-transmission"}) SET n.name = "Power transmission", n.description = "Transfers power from the driver to the pump: gearbox, coupling, motor side.";
MERGE (n:Subunit {id: "subunit:pumping-unit"}) SET n.name = "Pumping unit", n.description = "The hydraulic end: impeller, shaft, casing, seals and internal wear parts.";
MERGE (n:Subunit {id: "subunit:control-and-monitoring"}) SET n.name = "Control and monitoring", n.description = "Instrumentation, control units and condition monitoring devices.";
MERGE (n:Subunit {id: "subunit:lubrication-system"}) SET n.name = "Lubrication system", n.description = "Lube oil supply: pump, filter and cooler for the bearings.";
MERGE (n:Subunit {id: "subunit:miscellaneous"}) SET n.name = "Miscellaneous", n.description = "Supporting parts: base frame, piping, valves and auxiliary systems.";

// ---- Component (BB1 maintainable items) -------------------------------------
MERGE (n:Component {id: "component:impeller"}) SET n.name = "Impeller", n.description = "Rotating hydraulic element imparting energy to the fluid.";
MERGE (n:Component {id: "component:shaft"}) SET n.name = "Shaft", n.description = "Rotating shaft carrying impeller and transmitting torque.";
MERGE (n:Component {id: "component:casing"}) SET n.name = "Casing", n.description = "Pressure-containing pump body and volute.";
MERGE (n:Component {id: "component:radial-bearing"}) SET n.name = "Radial bearing", n.description = "Carries radial shaft loads.";
MERGE (n:Component {id: "component:thrust-bearing"}) SET n.name = "Thrust bearing", n.description = "Carries axial shaft loads.";
MERGE (n:Component {id: "component:mechanical-seal"}) SET n.name = "Mechanical seal", n.description = "Dynamic shaft seal against process medium.";
MERGE (n:Component {id: "component:packing"}) SET n.name = "Packing", n.description = "Gland packing as alternative shaft sealing.";
MERGE (n:Component {id: "component:wear-ring"}) SET n.name = "Wear ring", n.description = "Replaceable ring setting internal running clearance.";
MERGE (n:Component {id: "component:coupling"}) SET n.name = "Coupling", n.description = "Connects driver shaft to pump shaft.";
MERGE (n:Component {id: "component:gearbox"}) SET n.name = "Gearbox", n.description = "Speed-changing gear between driver and pump.";
MERGE (n:Component {id: "component:motor"}) SET n.name = "Motor", n.description = "Electric driver of the pump.";
MERGE (n:Component {id: "component:base-frame"}) SET n.name = "Base frame", n.description = "Common baseplate carrying pump and driver.";
MERGE (n:Component {id: "component:suction-strainer"}) SET n.name = "Suction strainer", n.description = "Protects the pump from ingested debris.";
MERGE (n:Component {id: "component:piping"}) SET n.name = "Piping", n.description = "Suction and discharge piping within the boundary.";
MERGE (n:Component {id: "component:valve"}) SET n.name = "Valve", n.description = "Isolation and check valves within the boundary.";
MERGE (n:Component {id: "component:lube-oil-pump"}) SET n.name = "Lube oil pump", n.description = "Circulates lubricating oil to the bearings.";
MERGE (n:Component {id: "component:oil-filter"}) SET n.name = "Oil filter", n.description = "Removes particles from the lube oil.";
MERGE (n:Component {id: "component:oil-cooler"}) SET n.name = "Oil cooler", n.description = "Removes heat from the lube oil.";
MERGE (n:Component {id: "component:pressure-instrument"}) SET n.name = "Pressure instrument", n.description = "Measures suction/discharge pressure.";
MERGE (n:Component {id: "component:temperature-instrument"}) SET n.name = "Temperature instrument", n.description = "Measures bearing or fluid temperature.";
MERGE (n:Component {id: "component:vibration-probe"}) SET n.name = "Vibration probe", n.description = "Measures shaft or casing vibration.";
MERGE (n:Component {id: "component:flow-instrument"}) SET n.name = "Flow instrument", n.description = "Measures delivered flow.";
MERGE (n:Component {id: "component:control-unit"}) SET n.name = "Control unit", n.description = "Local control logic for the pump unit.";
MERGE (n:Component {id: "component:actuating-device"}) SET n.name = "Actuating device", n.description = "Actuators operating valves or controls.";
MERGE (n:Component {id: "component:monitoring-device"}) SET n.name = "Monitoring device", n.description = "Condition monitoring and alarm device.";
MERGE (n:Component {id: "component:cabling"}) SET n.name = "Cabling", n.description = "Power and signal cabling and junction boxes.";
MERGE (n:Component {id: "component:seal-flush-system"}) SET n.name = "Seal flush system", n.description = "Flush/barrier fluid supply to the shaft seal.";
MERGE (n:Component {id: "component:cooling-water-system"}) SET n.name = "Cooling water system", n.description = "Cooling water supply within the boundary.";
MERGE (n:Component {id: "component:balance-drum"}) SET n.name = "Balance drum", n.description = "Axial thrust balancing device.";
MERGE (n:Component {id: "component:shaft-seal-gas-system"}) SET n.name = "Shaft seal gas system", n.description = "Buffer/seal gas supply to the shaft seal.";
MERGE (n:Component {id: "component:inducer"}) SET n.name = "Inducer", n.description = "Axial-flow first stage improving suction performance.";
MERGE (n:Component {id: "component:diffuser"}) SET n.name = "Diffuser", n.description = "Stationary vanes converting velocity to pressure.";
MERGE (n:Component {id: "component:bearing-housing"}) SET n.name = "Bearing housing", n.description = "Houses bearings and retains the oil sump.";
MERGE (n:Component {id: "component:oil-seal"}) SET n.name = "Oil seal", n.description = "Lip or labyrinth seal retaining bearing lubricant.";
MERGE (n:Component {id: "component:gasket"}) SET n.name = "Gasket", n.description = "Static sealing element between casing joints and flanges.";
MERGE (n:Component {id: "component:shaft-sleeve"}) SET n.name = "Shaft sleeve", n.description = "Replaceable sleeve protecting the shaft at seal and packing areas.";
MERGE (n:Component {id: "component:lantern-ring"}) SET n.name = "Lantern ring", n.description = "Spacer ring distributing flush liquid within the packing.";
MERGE (n:Component {id: "component:throat-bushing"}) SET n.name = "Throat bushing", n.description = "Close-clearance bushing restricting flow into the seal chamber.";
MERGE (n:Component {id: "component:expansion-joint"}) SET n.name = "Expansion joint", n.description = "Absorbs piping thermal movement at the pump nozzles.";
MERGE (n:Component {id: "component:foundation-bolt"}) SET n.name = "Foundation bolt", n.description = "Anchors the base frame to the foundation.";
MERGE (n:Component {id: "component:junction-box"}) SET n.name = "Junction box", n.description = "Terminates and distributes field power and signal wiring.";
MERGE (n:Component {id: "component:local-gauge"}) SET n.name = "Local gauge", n.description = "Locally mounted pressure or temperature gauge.";

// ---- BB1 HAS_SUBUNIT --------------------------------------------------------
MATCH (a:EquipmentClass {id: "equipment-class:bb1"})
UNWIND ["subunit:power-transmission", "subunit:pumping-unit", "subunit:control-and-monitoring", "subunit:lubrication-system", "subunit:miscellaneous"] AS dst_id
MATCH (b:Subunit {id: dst_id})
MERGE (a)-[:HAS_SUBUNIT]->(b);

// ---- Subunit HAS_COMPONENT --------------------------------------------------
MATCH (a:Subunit {id: "subunit:pumping-unit"})
UNWIND ["component:impeller", "component:shaft", "component:casing", "component:wear-ring", "component:mechanical-seal", "component:packing", "component:suction-strainer", "component:balance-drum", "component:shaft-seal-gas-system", "component:radial-bearing", "component:thrust-bearing", "component:inducer", "component:diffuser", "component:shaft-sleeve", "component:lantern-ring", "component:throat-bushing", "component:gasket"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:HAS_COMPONENT]->(b);
MATCH (a:Subunit {id: "subunit:power-transmission"})
UNWIND ["component:coupling", "component:gearbox", "component:motor", "component:cabling", "component:bearing-housing", "component:oil-seal"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:HAS_COMPONENT]->(b);
MATCH (a:Subunit {id: "subunit:lubrication-system"})
UNWIND ["component:lube-oil-pump", "component:oil-filter", "component:oil-cooler"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:HAS_COMPONENT]->(b);
MATCH (a:Subunit {id: "subunit:control-and-monitoring"})
UNWIND ["component:pressure-instrument", "component:temperature-instrument", "component:vibration-probe", "component:flow-instrument", "component:control-unit", "component:actuating-device", "component:monitoring-device", "component:junction-box", "component:local-gauge"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:HAS_COMPONENT]->(b);
MATCH (a:Subunit {id: "subunit:miscellaneous"})
UNWIND ["component:base-frame", "component:piping", "component:valve", "component:cooling-water-system", "component:seal-flush-system", "component:expansion-joint", "component:foundation-bolt"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:HAS_COMPONENT]->(b);

// ---- BB1 CAN_EXHIBIT every failure mode -------------------------------------
MATCH (a:EquipmentClass {id: "equipment-class:bb1"})
UNWIND ["failure-mode:brd", "failure-mode:ero", "failure-mode:hio", "failure-mode:loo", "failure-mode:vib", "failure-mode:lbp", "failure-mode:lcp", "failure-mode:std", "failure-mode:ohe", "failure-mode:elp", "failure-mode:elu", "failure-mode:fof", "failure-mode:inl", "failure-mode:noi", "failure-mode:oth", "failure-mode:pde", "failure-mode:plu", "failure-mode:ser", "failure-mode:unk"] AS dst_id
MATCH (b:FailureMode {id: dst_id})
MERGE (a)-[:CAN_EXHIBIT]->(b);

// ---- FailureMode CAUSED_BY FailureMechanism ---------------------------------
MATCH (a:FailureMode {id: "failure-mode:vib"})
UNWIND ["failure-mechanism:cavitation", "failure-mechanism:misalignment", "failure-mechanism:imbalance", "failure-mechanism:bearing-wear", "failure-mechanism:looseness"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:elp"})
UNWIND ["failure-mechanism:seal-failure", "failure-mechanism:corrosion", "failure-mechanism:wear"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:lbp"})
UNWIND ["failure-mechanism:seal-failure", "failure-mechanism:corrosion", "failure-mechanism:wear"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:ohe"})
UNWIND ["failure-mechanism:lubrication-failure", "failure-mechanism:bearing-wear", "failure-mechanism:overheating", "failure-mechanism:fouling"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:brd"})
UNWIND ["failure-mechanism:breakage", "failure-mechanism:fatigue", "failure-mechanism:overheating", "failure-mechanism:overload"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:inl"})
UNWIND ["failure-mechanism:wear", "failure-mechanism:erosion", "failure-mechanism:seal-failure"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:plu"})
UNWIND ["failure-mechanism:blockage", "failure-mechanism:contamination"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:ero"})
UNWIND ["failure-mechanism:control-failure", "failure-mechanism:faulty-signal", "failure-mechanism:cavitation"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:noi"})
UNWIND ["failure-mechanism:cavitation", "failure-mechanism:bearing-wear", "failure-mechanism:looseness", "failure-mechanism:loose-connection"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:std"})
UNWIND ["failure-mechanism:deformation", "failure-mechanism:corrosion", "failure-mechanism:fatigue", "failure-mechanism:cracking"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:fof"})
UNWIND ["failure-mechanism:no-power", "failure-mechanism:control-failure", "failure-mechanism:sticking"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:pde"})
UNWIND ["failure-mechanism:faulty-signal", "failure-mechanism:instrument-failure", "failure-mechanism:control-failure", "failure-mechanism:calibration-drift"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:loo"})
UNWIND ["failure-mechanism:wear", "failure-mechanism:blockage", "failure-mechanism:leakage"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:hio"})
UNWIND ["failure-mechanism:control-failure", "failure-mechanism:faulty-signal"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:lcp"})
UNWIND ["failure-mechanism:seal-failure", "failure-mechanism:leakage", "failure-mechanism:corrosion"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:elu"})
UNWIND ["failure-mechanism:seal-failure", "failure-mechanism:leakage", "failure-mechanism:corrosion"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:ser"})
UNWIND ["failure-mechanism:looseness", "failure-mechanism:contamination", "failure-mechanism:ageing"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:oth"})
UNWIND ["failure-mechanism:external-influence", "failure-mechanism:ageing"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:unk"})
UNWIND ["failure-mechanism:external-influence", "failure-mechanism:contamination"] AS dst_id
MATCH (b:FailureMechanism {id: dst_id})
MERGE (a)-[:CAUSED_BY]->(b);

// ---- FailureMechanism OCCURS_IN Component -----------------------------------
MATCH (a:FailureMechanism {id: "failure-mechanism:mechanical-failure"})
UNWIND ["component:shaft", "component:coupling", "component:impeller"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:leakage"})
UNWIND ["component:mechanical-seal", "component:casing", "component:piping"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:vibration"})
UNWIND ["component:shaft", "component:radial-bearing", "component:base-frame"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:clearance-alignment-failure"})
UNWIND ["component:wear-ring", "component:coupling", "component:shaft"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:deformation"})
UNWIND ["component:casing", "component:shaft", "component:base-frame"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:looseness"})
UNWIND ["component:coupling", "component:base-frame"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:sticking"})
UNWIND ["component:valve", "component:actuating-device"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:material-failure"})
UNWIND ["component:impeller", "component:casing", "component:shaft"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:cavitation"})
UNWIND ["component:impeller", "component:casing"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:corrosion"})
UNWIND ["component:casing", "component:piping", "component:impeller"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:erosion"})
UNWIND ["component:impeller", "component:wear-ring", "component:casing"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:wear"})
UNWIND ["component:wear-ring", "component:radial-bearing", "component:thrust-bearing", "component:packing"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:breakage"})
UNWIND ["component:shaft", "component:impeller", "component:coupling"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:fatigue"})
UNWIND ["component:shaft", "component:coupling"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:overheating"})
UNWIND ["component:radial-bearing", "component:thrust-bearing", "component:motor"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:burst"})
UNWIND ["component:casing", "component:piping"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:instrument-failure"})
UNWIND ["component:pressure-instrument", "component:temperature-instrument", "component:flow-instrument", "component:vibration-probe"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:control-failure"})
UNWIND ["component:control-unit", "component:actuating-device"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:no-signal"})
UNWIND ["component:vibration-probe", "component:cabling", "component:monitoring-device"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:faulty-signal"})
UNWIND ["component:pressure-instrument", "component:flow-instrument", "component:cabling"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:software-failure"})
UNWIND ["component:control-unit", "component:monitoring-device"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:electrical-failure"})
UNWIND ["component:motor", "component:cabling", "component:control-unit"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:short-circuit"})
UNWIND ["component:motor", "component:cabling"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:open-circuit"})
UNWIND ["component:cabling", "component:motor"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:no-power"})
UNWIND ["component:motor", "component:cabling"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:faulty-power"})
UNWIND ["component:motor", "component:control-unit"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:earth-fault"})
UNWIND ["component:motor", "component:cabling"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:external-influence"})
UNWIND ["component:piping", "component:base-frame", "component:suction-strainer"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:blockage"})
UNWIND ["component:suction-strainer", "component:piping", "component:oil-filter"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:contamination"})
UNWIND ["component:lube-oil-pump", "component:oil-filter", "component:mechanical-seal"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:misalignment"})
UNWIND ["component:coupling", "component:shaft"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:imbalance"})
UNWIND ["component:impeller", "component:shaft"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:bearing-wear"})
UNWIND ["component:radial-bearing", "component:thrust-bearing"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:seal-failure"})
UNWIND ["component:mechanical-seal", "component:packing", "component:seal-flush-system"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:lubrication-failure"})
UNWIND ["component:lube-oil-pump", "component:oil-filter", "component:radial-bearing"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:fouling"})
UNWIND ["component:oil-cooler", "component:suction-strainer"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:overload"})
UNWIND ["component:motor", "component:shaft"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:cracking"})
UNWIND ["component:casing", "component:impeller"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:loose-connection"})
UNWIND ["component:cabling", "component:junction-box"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:calibration-drift"})
UNWIND ["component:pressure-instrument", "component:local-gauge"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);
MATCH (a:FailureMechanism {id: "failure-mechanism:ageing"})
UNWIND ["component:gasket", "component:oil-seal"] AS dst_id
MATCH (b:Component {id: dst_id})
MERGE (a)-[:OCCURS_IN]->(b);

// ---- FailureMode REMEDIED_BY MaintenanceActivity ----------------------------
MATCH (a:FailureMode {id: "failure-mode:vib"})
UNWIND ["maintenance-activity:adjust", "maintenance-activity:overhaul", "maintenance-activity:inspect"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:brd"})
UNWIND ["maintenance-activity:overhaul", "maintenance-activity:replace"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:ero"})
UNWIND ["maintenance-activity:adjust", "maintenance-activity:repair"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:hio"})
UNWIND ["maintenance-activity:adjust", "maintenance-activity:check"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:loo"})
UNWIND ["maintenance-activity:clean", "maintenance-activity:repair", "maintenance-activity:inspect"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:lbp"})
UNWIND ["maintenance-activity:replace", "maintenance-activity:repair"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:lcp"})
UNWIND ["maintenance-activity:replace", "maintenance-activity:repair"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:std"})
UNWIND ["maintenance-activity:repair", "maintenance-activity:modify"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:ohe"})
UNWIND ["maintenance-activity:lubricate", "maintenance-activity:inspect", "maintenance-activity:repair"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:elp"})
UNWIND ["maintenance-activity:replace", "maintenance-activity:repair"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:elu"})
UNWIND ["maintenance-activity:replace", "maintenance-activity:repair"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:fof"})
UNWIND ["maintenance-activity:test", "maintenance-activity:repair"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:inl"})
UNWIND ["maintenance-activity:overhaul", "maintenance-activity:replace"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:noi"})
UNWIND ["maintenance-activity:inspect", "maintenance-activity:adjust"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:oth"})
UNWIND ["maintenance-activity:check"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:pde"})
UNWIND ["maintenance-activity:check", "maintenance-activity:adjust"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:plu"})
UNWIND ["maintenance-activity:clean", "maintenance-activity:inspect"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:ser"})
UNWIND ["maintenance-activity:service", "maintenance-activity:adjust", "maintenance-activity:refit"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
MATCH (a:FailureMode {id: "failure-mode:unk"})
UNWIND ["maintenance-activity:inspect", "maintenance-activity:check"] AS dst_id
MATCH (b:MaintenanceActivity {id: dst_id})
MERGE (a)-[:REMEDIED_BY]->(b);
