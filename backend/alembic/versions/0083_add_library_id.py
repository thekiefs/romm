"""Add library_id to roms, rom_files, and firmware

Revision ID: 0083_add_library_id
Revises: 0082_save_origin_device
Create Date: 2026-06-18 00:00:00.000000

"""

import hashlib
import os

import sqlalchemy as sa
from alembic import op

from config import LIBRARY_BASE_PATH

revision = "0083_add_library_id"
down_revision = "0082_save_origin_device"
branch_labels = None
depends_on = None

def get_default_library_id() -> str:
    # Deterministic ID for the default library path
    return hashlib.sha1(LIBRARY_BASE_PATH.encode("utf-8")).hexdigest()[:12]

def upgrade() -> None:
    default_id = get_default_library_id()

    # Step 1: Add columns as nullable
    for table in ["roms", "rom_files", "firmware"]:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("library_id", sa.String(length=12), nullable=True)
            )

    # Step 2: Backfill existing rows
    # Using SQLAlchemy's raw update execution to bypass ORM
    roms_t = sa.table("roms", sa.column("library_id", sa.String))
    rom_files_t = sa.table("rom_files", sa.column("library_id", sa.String))
    firmware_t = sa.table("firmware", sa.column("library_id", sa.String))

    op.execute(roms_t.update().values(library_id=default_id))
    op.execute(rom_files_t.update().values(library_id=default_id))
    op.execute(firmware_t.update().values(library_id=default_id))

    # Step 3: Make non-nullable and add index
    for table in ["roms", "rom_files", "firmware"]:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column("library_id", existing_type=sa.String(length=12), nullable=False)
            batch_op.create_index(f"ix_{table}_library_id", ["library_id"])


def downgrade() -> None:
    for table in ["roms", "rom_files", "firmware"]:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table}_library_id")
            batch_op.drop_column("library_id")
