"""initial schema

Tables: work_items, call_sessions, dispositions, audit_log, payor_profiles.

Revision ID: f703a8144e79
Revises:
Create Date: 2026-04-21 20:56:19.621964

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f703a8144e79"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- work_items ---
    op.create_table(
        "work_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("use_case", sa.String(32), nullable=False),
        sa.Column("payor", sa.String(128), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("context", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_work_items_status", "work_items", ["status"])
    op.create_index("ix_work_items_status_priority", "work_items", ["status", "priority"])
    op.create_index("ix_work_items_next_retry", "work_items", ["next_retry_at"])

    # --- call_sessions ---
    op.create_table(
        "call_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("work_item_id", sa.String(64), nullable=False),
        sa.Column("call_sid", sa.String(64)),
        sa.Column("state", sa.String(20), nullable=False, server_default="pre_call"),
        sa.Column("payor", sa.String(128), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("from_number", sa.String(20)),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("hold_duration_s", sa.Float, nullable=False, server_default="0"),
        sa.Column("conversation_duration_s", sa.Float, nullable=False, server_default="0"),
        sa.Column("recording_url", sa.Text),
        sa.Column("error", sa.Text),
    )
    op.create_index("ix_call_sessions_work_item", "call_sessions", ["work_item_id"])
    op.create_index("ix_call_sessions_call_sid", "call_sessions", ["call_sid"])

    # --- dispositions ---
    op.create_table(
        "dispositions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("work_item_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("use_case", sa.String(32), nullable=False),
        sa.Column("payor", sa.String(128), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("extracted_entities", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("entities_verified", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("escalation_reason", sa.String(64)),
        sa.Column("rep_name", sa.String(128)),
        sa.Column("reference_number", sa.String(64)),
        sa.Column("confidence_score", sa.Float, nullable=False, server_default="0"),
        sa.Column("transcript", sa.Text),
        sa.Column("recording_url", sa.Text),
        sa.Column("retry_needed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("next_action", sa.String(20), nullable=False, server_default="none"),
        sa.Column("call_start", sa.DateTime(timezone=True)),
        sa.Column("call_end", sa.DateTime(timezone=True)),
        sa.Column("hold_duration_s", sa.Float, nullable=False, server_default="0"),
        sa.Column("conversation_duration_s", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_dispositions_work_item", "dispositions", ["work_item_id"])
    op.create_index("ix_dispositions_session", "dispositions", ["session_id"])

    # --- audit_log (immutable — no UPDATE/DELETE allowed by convention) ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("work_item_id", sa.String(64)),
        sa.Column("session_id", sa.String(64)),
        sa.Column("call_sid", sa.String(64)),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payor", sa.String(128)),
        sa.Column("phi_fields_disclosed", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("details", sa.JSON, nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_log_work_item", "audit_log", ["work_item_id"])
    op.create_index("ix_audit_log_session", "audit_log", ["session_id"])
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_ts_event", "audit_log", ["timestamp", "event_type"])

    # --- payor_profiles ---
    op.create_table(
        "payor_profiles",
        sa.Column("name", sa.String(128), primary_key=True),
        sa.Column("phone_numbers", sa.JSON, nullable=False, server_default="{}"),
        sa.Column(
            "timezone", sa.String(64), nullable=False, server_default="'America/New_York'"
        ),
        sa.Column("business_hours", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("max_hold_minutes", sa.Integer, nullable=False, server_default="90"),
        sa.Column("max_concurrent_calls", sa.Integer, nullable=False, server_default="5"),
        sa.Column("ai_disclosure_required", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("ivr_config", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("payor_profiles")
    op.drop_table("audit_log")
    op.drop_table("dispositions")
    op.drop_table("call_sessions")
    op.drop_table("work_items")
