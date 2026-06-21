#!/usr/bin/env python3
"""One-time migration script: detect the legacy Structure A/B layout and
append an equivalent ``libraries:`` block to ``config.yml``.

Usage (inside the container)::

    docker exec romm python backend/scripts/migrate_library_structure.py
    docker exec romm python backend/scripts/migrate_library_structure.py --dry-run
    docker exec romm python backend/scripts/migrate_library_structure.py --config /path/to/config.yml

The script is idempotent: if ``config.yml`` already contains a ``libraries:``
block it exits without making changes.  When not in ``--dry-run`` mode it
backs up the existing file to ``config.yml.bak`` before writing.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml

# Allow running from a checkout where ``backend`` is not on sys.path.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND_DIR))

from config import LIBRARY_BASE_PATH  # noqa: E402
from config.config_manager import (  # noqa: E402
    ROMM_USER_CONFIG_FILE,
    config_manager,
)


def detect_structure(library_path: str, roms_folder: str) -> str:
    """Classify the on-disk layout as ``"A"``, ``"B"``, or ``"Flat"``.

    * Structure A: ``<library>/roms/<platform>/`` — a top-level ``roms``
      directory contains platform sub-directories.
    * Structure B: ``<library>/<platform>/roms/`` — at least one top-level
      directory contains a ``roms`` sub-directory.
    * Flat: neither pattern matched.
    """
    # Structure A: <library>/roms/<platform>
    roms_root = os.path.join(library_path, roms_folder)
    if os.path.isdir(roms_root):
        try:
            if any(
                os.path.isdir(os.path.join(roms_root, d))
                for d in os.listdir(roms_root)
            ):
                return "A"
        except PermissionError:
            pass

    # Structure B: <library>/<platform>/roms
    try:
        for d in os.listdir(library_path):
            platform_path = os.path.join(library_path, d)
            if os.path.isdir(platform_path) and os.path.isdir(
                os.path.join(platform_path, roms_folder)
            ):
                return "B"
    except PermissionError:
        pass

    return "Flat"


STRUCTURE_TEMPLATES = {
    "A": "roms/{platformDir}/{gameFile}",
    "B": "{platformDir}/roms/{gameFile}",
    "Flat": "{platformDir}/{gameFile}",
}


def migrate(config_file: str, dry_run: bool) -> int:
    """Run the migration.  Returns a process exit code."""
    print(f"Config file : {config_file}")
    print(f"Dry run     : {dry_run}")

    # 1. Idempotency check
    if not os.path.exists(config_file):
        print(f"Config file not found. Nothing to migrate.")
        return 0

    with open(config_file, "r") as f:
        raw_config = yaml.safe_load(f) or {}

    if "libraries" in raw_config:
        print(
            "Config already contains a 'libraries' block. "
            "Skipping migration to avoid overwriting user settings."
        )
        return 0

    # 2. Detect structure
    cnfg = config_manager.get_config()
    roms_folder = cnfg.ROMS_FOLDER_NAME
    library_path = str(Path(LIBRARY_BASE_PATH).resolve())

    print(f"Library path: {library_path}")
    print(f"Roms folder : {roms_folder}")

    structure_type = detect_structure(library_path, roms_folder)
    structure_template = STRUCTURE_TEMPLATES[structure_type]

    print(f"Detected    : Structure {structure_type}")
    print(f"Template    : {structure_template}")

    new_libraries = [
        {
            "name": "Main Library",
            "path": library_path,
            "structure": structure_template,
        }
    ]
    raw_config["libraries"] = new_libraries

    if dry_run:
        print("\n--- dry-run preview (config.yml) ---")
        yaml.dump(raw_config, sys.stdout, default_flow_style=False, sort_keys=False)
        print("--- end preview ---")
        print("\nNo files were modified (dry-run mode).")
        return 0

    # 3. Backup
    backup_path = f"{config_file}.bak"
    print(f"Backing up  : {backup_path}")
    shutil.copy2(config_file, backup_path)

    # 4. Write
    print(f"Writing     : {config_file}")
    with open(config_file, "w") as f:
        yaml.dump(raw_config, f, default_flow_style=False, sort_keys=False)

    print("Migration completed successfully.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate legacy Structure A/B layout to a libraries: block in config.yml.",
    )
    parser.add_argument(
        "--config",
        default=ROMM_USER_CONFIG_FILE,
        help="Path to config.yml (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resulting config.yml without writing anything.",
    )
    args = parser.parse_args(argv)

    return migrate(config_file=args.config, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
