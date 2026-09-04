from sqlalchemy import text

from .db import Base, engine

DIRECT_TENANT_TABLES = (
    "tenant_memberships",
    "policy_configs",
    "tool_connections",
    "capability_manifests",
    "connection_requirements",
    "connector_packages",
    "connector_installations",
    "connector_installation_versions",
    "polling_subscriptions",
    "polling_deliveries",
    "webhook_subscriptions",
    "webhook_deliveries",
    "tool_trust_states",
    "workflows",
    "workflow_schedules",
    "workspace_records",
    "workflow_runs",
    "plan_versions",
    "approval_snapshots",
    "step_attempts",
    "dead_letter_entries",
    "artifacts",
    "audit_events",
)

CHILD_TENANT_TABLES = {
    "run_steps": "run_id",
    "approvals": "run_id",
}


async def migrate_database() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    # New databases receive the complete enum from SQLAlchemy's metadata. Existing
    # databases need the new values appended after the type is known to exist.
    if engine.dialect.name == "postgresql":
        async with engine.begin() as connection:
            await connection.execute(
                text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS external_organization_id VARCHAR(240)")
            )
            await connection.execute(
                text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS created_by VARCHAR(240)")
            )
            await connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_workspaces_external_organization_id ON workspaces (external_organization_id)")
            )
            await connection.execute(
                text("ALTER TABLE workflows ADD COLUMN IF NOT EXISTS variables JSON DEFAULT '{}'::json")
            )
            await connection.execute(
                text("ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS inputs JSON DEFAULT '{}'::json")
            )
            await connection.execute(
                text("ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS execution_context JSON DEFAULT '{}'::json")
            )
            await connection.execute(
                text("ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS cancellation_requested BOOLEAN DEFAULT FALSE")
            )
            await connection.execute(
                text("ALTER TABLE workflow_runs ADD COLUMN IF NOT EXISTS request_key VARCHAR(200)")
            )
            await connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS uq_workspace_run_request ON workflow_runs (workspace_id, request_key) WHERE request_key IS NOT NULL")
            )
            await connection.execute(
                text("ALTER TABLE run_steps ADD COLUMN IF NOT EXISTS step_key VARCHAR(120)")
            )
            await connection.execute(
                text("ALTER TABLE run_steps ADD COLUMN IF NOT EXISTS depends_on JSON DEFAULT '[]'::json")
            )
            await connection.execute(
                text("ALTER TABLE run_steps ADD COLUMN IF NOT EXISTS condition JSON")
            )
            await connection.execute(
                text("ALTER TABLE run_steps ADD COLUMN IF NOT EXISTS dependency_mode VARCHAR(30) DEFAULT 'all_succeeded'")
            )
            await connection.execute(
                text("ALTER TABLE run_steps ADD COLUMN IF NOT EXISTS output_variables JSON DEFAULT '{}'::json")
            )
            await connection.execute(
                text("UPDATE run_steps SET step_key = 'step_' || (position + 1) WHERE step_key IS NULL")
            )
            await connection.execute(
                text("ALTER TABLE polling_subscriptions ADD COLUMN IF NOT EXISTS checkpoint JSON DEFAULT '{}'::json")
            )
            await connection.execute(
                text("ALTER TABLE polling_subscriptions ADD COLUMN IF NOT EXISTS checkpoint_path VARCHAR(500)")
            )
            await connection.execute(
                text("ALTER TABLE polling_subscriptions ADD COLUMN IF NOT EXISTS cursor_argument VARCHAR(200)")
            )
            await connection.execute(
                text("ALTER TABLE polling_deliveries ADD COLUMN IF NOT EXISTS checkpoint JSON DEFAULT '{}'::json")
            )
            await connection.execute(
                text("ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS payload JSON DEFAULT '{}'::json")
            )
            await connection.execute(
                text("ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS replay_of_id VARCHAR(36)")
            )
            await connection.execute(
                text("ALTER TABLE webhook_deliveries ADD COLUMN IF NOT EXISTS replay_count INTEGER DEFAULT 0")
            )
            for value in ("waiting_for_action", "recovering", "blocked"):
                await connection.execute(
                    text(f"ALTER TYPE runstatus ADD VALUE IF NOT EXISTS '{value}'")
                )
            for value in ("agent", "plugin", "webhook", "browser"):
                await connection.execute(
                    text(f"ALTER TYPE toolkind ADD VALUE IF NOT EXISTS '{value}'")
                )

    if engine.dialect.name != "postgresql":
        return

    async with engine.begin() as connection:
        for table in DIRECT_TENANT_TABLES:
            await connection.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            await connection.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            await connection.execute(
                text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            )
            await connection.execute(
                text(
                    f'CREATE POLICY tenant_isolation ON "{table}" '
                    "USING (workspace_id::text = current_setting('app.tenant_id', true)) "
                    "WITH CHECK (workspace_id::text = current_setting('app.tenant_id', true))"
                )
            )

        for table, run_column in CHILD_TENANT_TABLES.items():
            await connection.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            await connection.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            await connection.execute(
                text(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
            )
            await connection.execute(
                text(
                    f'CREATE POLICY tenant_isolation ON "{table}" USING ('
                    f'EXISTS (SELECT 1 FROM workflow_runs r WHERE r.id = "{table}".{run_column} '
                    "AND r.workspace_id::text = current_setting('app.tenant_id', true)))"
                )
            )

        await connection.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION reject_immutable_record_change()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'immutable governance record cannot be changed';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        await connection.execute(
            text("DROP TRIGGER IF EXISTS connector_installation_versions_immutable ON connector_installation_versions")
        )
        await connection.execute(
            text(
                "CREATE TRIGGER connector_installation_versions_immutable "
                "BEFORE UPDATE OR DELETE ON connector_installation_versions FOR EACH ROW "
                "EXECUTE FUNCTION reject_immutable_record_change()"
            )
        )
        await connection.execute(
            text("DROP TRIGGER IF EXISTS published_connector_packages_immutable ON connector_packages")
        )
        await connection.execute(
            text(
                "CREATE TRIGGER published_connector_packages_immutable "
                "BEFORE UPDATE OR DELETE ON connector_packages FOR EACH ROW "
                "WHEN (OLD.status = 'published') "
                "EXECUTE FUNCTION reject_immutable_record_change()"
            )
        )
        await connection.execute(
            text("DROP TRIGGER IF EXISTS approval_snapshots_immutable ON approval_snapshots")
        )
        await connection.execute(
            text(
                "CREATE TRIGGER approval_snapshots_immutable "
                "BEFORE UPDATE OR DELETE ON approval_snapshots FOR EACH ROW "
                "EXECUTE FUNCTION reject_immutable_record_change()"
            )
        )
        await connection.execute(
            text("DROP TRIGGER IF EXISTS approved_plan_versions_immutable ON plan_versions")
        )
        await connection.execute(
            text(
                "CREATE TRIGGER approved_plan_versions_immutable "
                "BEFORE UPDATE OR DELETE ON plan_versions FOR EACH ROW "
                "WHEN (OLD.status = 'approved') "
                "EXECUTE FUNCTION reject_immutable_record_change()"
            )
        )
