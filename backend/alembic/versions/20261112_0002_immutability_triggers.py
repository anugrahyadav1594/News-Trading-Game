"""Add PostgreSQL immutability triggers for financial ledgers, trades, and audit logs

Revision ID: 20261112_0002
Revises: 12131e0d45fa
Create Date: 2026-11-12 20:19:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "20261112_0002"
down_revision: Union[str, None] = "12131e0d45fa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IMMUTABLE_TABLES = (
    "cash_ledger_entries",
    "share_ledger_entries",
    "trades",
    "audit_logs",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION mtt_prevent_immutable_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'MTT Accounting Integrity Violation: Table % is append-only immutable (% prohibited).', TG_TABLE_NAME, TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table_name in IMMUTABLE_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION mtt_prevent_immutable_mutation();
            """
        )


def downgrade() -> None:
    for table_name in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name};")
    op.execute("DROP FUNCTION IF EXISTS mtt_prevent_immutable_mutation();")
