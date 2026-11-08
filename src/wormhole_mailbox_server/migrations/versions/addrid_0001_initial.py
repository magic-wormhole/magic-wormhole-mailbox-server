"""initial address-id schema

Revision ID: addrid_0001
Revises:
Create Date: 2026-11-08
"""

import sqlalchemy as sa


revision = "addrid_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(op):
    op.create_table(
        "address_ids",
        sa.Column("generation", sa.Integer()),
        sa.Column("counter", sa.Integer()),
        sa.Column("type", sa.String()),
        sa.Column("address", sa.String()),
        sa.Column("retain", sa.Integer()),
    )


def downgrade(op):
    op.drop_table("address_ids")
