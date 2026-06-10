"""rca_connector_opc_ua — the OPC UA connector (EPIC-013 S13.5).

opc_ua.get_current_values (on-demand asyncua read) + a background subscription
(SDK streaming primitives) for real-time current values with reconnect. Real-time
trigger source (historical evidence is PI). Product code: never imports rca_simulator.
"""
