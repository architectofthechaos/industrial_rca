"""connections table + alias rekey to connection_id (Sprint 2b §1.1/§1.2).

Breaking: drops asset_aliases.source_system + source_system_type and replaces them
with connection_id (TEXT NOT NULL, FK -> connections.connection_id). One forward
migration that also synthesizes a default `connections` row per distinct
(assets.plant_id, asset_aliases.source_system) seen in the existing data, then
backfills every alias's connection_id from that synth map. The backfill is the
riskiest step (risk callout #3): we add connection_id NULLABLE, fill it, and ASSERT
no NULL remains before flipping NOT NULL — a stray NULL aborts the migration loudly
rather than producing a half-rekeyed table.

Synth id scheme: `{plant_id}.{category}.{source.replace('_','-')}-default`, e.g.
`refinery-gc.cmms.maximo-default`, `refinery-gc.hierarchy.pi-af-default`,
`refinery-gc.historian.uns-default`. Legacy source -> (category, status, base_url):
  maximo  -> cmms       / active   / http://localhost:8002
  sap_pm  -> cmms       / disabled / http://localhost:8003   (parked: avoids the
             one-active-per-(plant, category) cmms clash with maximo)
  pi_af   -> hierarchy  / active   / http://localhost:8001
  uns     -> historian  / active   / mqtt://localhost:1883
An empty DB (no aliases) synthesizes nothing — fine.

Revision ID: 0003_connections
Revises: 0002_phase1_alignment
Create Date: 2026-06-11
"""
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_connections"
down_revision = "0002_phase1_alignment"
branch_labels = None
depends_on = None

# Legacy source key -> the synth connection's category / status / base_url / extra_config.
# Mirrors rca_mar.seed._DEFAULT_CONNECTION_SPECS; kept inline so the migration is
# self-contained and does not import app code that may drift.
_SOURCE_SPECS = {
    "maximo": {"category": "cmms", "status": "active",
               "base_url": "http://localhost:8002", "extra_config": None},
    "sap_pm": {"category": "cmms", "status": "disabled",
               "base_url": "http://localhost:8003", "extra_config": None},
    "pi_af": {"category": "hierarchy", "status": "active",
              "base_url": "http://localhost:8001",
              "extra_config": {"database_name": "Refinery-GC"}},
    "uns": {"category": "historian", "status": "active",
            "base_url": "mqtt://localhost:1883", "extra_config": None},
}


def _synth_connection_id(plant_id: str, source: str) -> str:
    return f"{plant_id}.{_SOURCE_SPECS[source]['category']}.{source.replace('_', '-')}-default"


def upgrade() -> None:
    # 1. connections table + the partial unique index (one active per plant/category).
    op.create_table(
        "connections",
        sa.Column("connection_id", sa.Text(), primary_key=True),
        sa.Column("plant_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("connector_type", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("auth_config", postgresql.JSONB(), nullable=False),
        sa.Column("extra_config", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_result", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index("ix_connections_plant_id", "connections", ["plant_id"])
    op.create_index("uq_connection_active_category", "connections", ["plant_id", "category"],
                    unique=True, postgresql_where=sa.text("status = 'active'"))

    bind = op.get_bind()

    # 2. Synthesize a default connection row per distinct (plant_id, source_system) in the
    #    existing data (JOIN aliases -> assets for plant_id). Empty DB -> nothing inserted.
    legacy_keys = bind.execute(sa.text(
        "SELECT DISTINCT a.plant_id AS plant_id, al.source_system AS source "
        "FROM asset_aliases al JOIN assets a ON a.asset_id = al.asset_id")).mappings().all()
    for row in legacy_keys:
        plant_id, source = row["plant_id"], row["source"]
        spec = _SOURCE_SPECS.get(source)
        if spec is None:
            # An unknown legacy source has no honest category/base_url; refuse to guess.
            raise RuntimeError(
                f"0003 backfill: unknown legacy source_system {source!r} for plant "
                f"{plant_id!r}; cannot synthesize a connection (known: "
                f"{sorted(_SOURCE_SPECS)})")
        bind.execute(
            sa.text(
                "INSERT INTO connections (connection_id, plant_id, category, connector_type, "
                "display_name, base_url, auth_config, extra_config, status) "
                "VALUES (:cid, :plant, :cat, :ctype, :dname, :burl, "
                "CAST(:auth AS jsonb), CAST(:extra AS jsonb), :status) "
                "ON CONFLICT (connection_id) DO NOTHING"),
            {"cid": _synth_connection_id(plant_id, source), "plant": plant_id,
             "cat": spec["category"], "ctype": source,
             "dname": f"{source} (default)", "burl": spec["base_url"],
             "auth": json.dumps({"type": "none", "secret_ref": None}),
             "extra": None if spec["extra_config"] is None else json.dumps(spec["extra_config"]),
             "status": spec["status"]})

    # 3. Add connection_id NULLABLE first.
    op.add_column("asset_aliases", sa.Column("connection_id", sa.Text(), nullable=True))

    # 4. Backfill each alias's connection_id from its (asset.plant_id, source_system). We
    #    build the synth id directly with a CASE for the category rather than joining
    #    `connections` — the UPDATE target `al` can't be re-listed in FROM, and the synth-id
    #    scheme is `{plant}.{category}.{source.replace('_','-')}-default`. An unmapped source
    #    leaves connection_id NULL, which the step-5 assertion then catches loudly.
    category_case = " ".join(
        f"WHEN al.source_system = '{src}' THEN '{spec['category']}'"
        for src, spec in _SOURCE_SPECS.items())
    bind.execute(sa.text(
        "UPDATE asset_aliases al SET connection_id = "
        "  a.plant_id || '.' || (CASE " + category_case + " END) || '.' || "
        "  replace(al.source_system, '_', '-') || '-default' "
        "FROM assets a "
        "WHERE al.asset_id = a.asset_id "
        "  AND al.source_system IN (" +
        ", ".join(f"'{src}'" for src in _SOURCE_SPECS) + ")"))

    # 5. Fail loud (risk callout #3) if any alias is still unmapped.
    null_count = bind.execute(sa.text(
        "SELECT count(*) FROM asset_aliases WHERE connection_id IS NULL")).scalar_one()
    if null_count:
        raise RuntimeError(
            f"0003 backfill left {null_count} asset_aliases row(s) with NULL connection_id; "
            "aborting (no source_system -> connection mapping). Inspect the data and the "
            "synth-id scheme before retrying.")

    # 6. connection_id NOT NULL + FK + index.
    op.alter_column("asset_aliases", "connection_id", nullable=False)
    op.create_foreign_key("fk_alias_connection", "asset_aliases", "connections",
                          ["connection_id"], ["connection_id"])
    op.create_index("ix_alias_connection", "asset_aliases", ["connection_id"])

    # 7. Swap the source_system-keyed indexes for connection_id-keyed ones.
    op.drop_index("uq_alias_active", table_name="asset_aliases")
    op.drop_index("ix_alias_lookup", table_name="asset_aliases")
    op.create_index("ix_alias_lookup", "asset_aliases",
                    ["tenant_id", "connection_id", "external_id"])
    op.create_index("uq_alias_active", "asset_aliases",
                    ["tenant_id", "connection_id", "external_id"],
                    unique=True, postgresql_where=sa.text("valid_to IS NULL"))

    # 8. Drop the legacy columns.
    op.drop_column("asset_aliases", "source_system_type")
    op.drop_column("asset_aliases", "source_system")


def downgrade() -> None:
    # Best-effort reverse (matches 0002's reversible house approach). Recreates the legacy
    # columns from the connection: source_system <- connector_type, source_system_type <-
    # the connection's category. Aliases pointing at a connection whose connector_type is no
    # longer a known legacy source cannot be honestly reversed.
    op.add_column("asset_aliases", sa.Column("source_system", sa.String(), nullable=True))
    op.add_column("asset_aliases", sa.Column("source_system_type", sa.Text(), nullable=True))

    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE asset_aliases al SET source_system = c.connector_type, "
        "  source_system_type = c.category "
        "FROM connections c WHERE c.connection_id = al.connection_id"))

    op.drop_index("uq_alias_active", table_name="asset_aliases")
    op.drop_index("ix_alias_lookup", table_name="asset_aliases")
    op.drop_index("ix_alias_connection", table_name="asset_aliases")
    op.drop_constraint("fk_alias_connection", "asset_aliases", type_="foreignkey")
    op.drop_column("asset_aliases", "connection_id")

    op.alter_column("asset_aliases", "source_system", nullable=False)
    op.alter_column("asset_aliases", "source_system_type", nullable=False)
    op.create_index("ix_alias_lookup", "asset_aliases",
                    ["tenant_id", "source_system", "external_id"])
    op.create_index("uq_alias_active", "asset_aliases",
                    ["tenant_id", "source_system", "external_id"],
                    unique=True, postgresql_where=sa.text("valid_to IS NULL"))

    op.drop_index("uq_connection_active_category", table_name="connections")
    op.drop_index("ix_connections_plant_id", table_name="connections")
    op.drop_table("connections")
