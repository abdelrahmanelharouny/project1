"""auth hardening: lockout, refresh token families, credential tokens (P0-2)

Revision ID: 0015_auth_hardening
Revises: 0014_merge_m6bc_m7
Create Date: 2026-11-04

Additive migration:

`users` — account lockout + email verification state:

- `failed_login_count` INT NOT NULL server_default "0" — consecutive failed
  password attempts; reset on success and when the lockout re-arms.
- `locked_until` TIMESTAMPTZ NULL — set when the failed-login threshold is
  reached; sign-in attempts inside the window are rejected with 423.
- `email_verified` BOOLEAN NOT NULL server_default true — registration gate.
  Sandboxes run with FIELDSHIFT_DEV_MODE=true which auto-verifies.

`auth_tokens` — refresh-token rotation families:

- `kind` VARCHAR(20) NOT NULL server_default "access" + CHECK
  `ck_auth_tokens_kind` IN ('access','refresh'). Only access tokens may
  authenticate API calls; refresh tokens exist solely for rotation.
- `family_id` UUID NULL — all tokens issued from one login/rotation chain
  share a family; reuse of a revoked refresh token revokes the whole family.

`credential_tokens` — single-use challenge tokens (password reset, email
verification). Only the SHA-256 hash is stored; rows are one-shot (used_at).

No existing data is rewritten. Downgrade reverses every change in order.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015_auth_hardening"
down_revision = "0014_merge_m6bc_m7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users: account lockout + email verification state
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # auth_tokens: access vs refresh kind + refresh rotation families
    op.add_column(
        "auth_tokens",
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="access"),
    )
    op.add_column(
        "auth_tokens",
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_auth_tokens_kind",
        "auth_tokens",
        "kind IN ('access','refresh')",
    )
    op.create_index("ix_auth_tokens_family", "auth_tokens", ["family_id"])

    # credential_tokens: single-use password-reset / email-verification challenges
    op.create_table(
        "credential_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "kind IN ('password_reset','email_verification')",
            name="ck_credential_tokens_kind",
        ),
    )
    op.create_index("uq_credential_tokens_hash", "credential_tokens", ["token_hash"], unique=True)
    op.create_index("ix_credential_tokens_user", "credential_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_credential_tokens_user", table_name="credential_tokens")
    op.drop_index("uq_credential_tokens_hash", table_name="credential_tokens")
    op.drop_table("credential_tokens")
    op.drop_index("ix_auth_tokens_family", table_name="auth_tokens")
    op.drop_constraint("ck_auth_tokens_kind", "auth_tokens", type_="check")
    op.drop_column("auth_tokens", "family_id")
    op.drop_column("auth_tokens", "kind")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
