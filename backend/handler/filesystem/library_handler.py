import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generator

from logger.logger import log

VALID_VARIABLES = {
    "{platformDir}",
    "{platformBios}",
    "{gameRegion}",
    "{gameDir}",
    "{gameFile}",
    "{gameCategory}",
}

VALID_CATEGORIES = {
    "retail",
    "dlc",
    "hack",
    "mod",
    "patch",
    "update",
    "demo",
    "translation",
    "prototype",
}


class LibraryValidationException(Exception):
    pass


class LibraryHandler:
    def __init__(self, libraries: list[dict[str, Any]]):
        self.libraries = libraries

    def get_valid_libraries(self) -> list[dict[str, Any]]:
        valid_libraries = []
        for lib in self.libraries:
            try:
                self.validate_library(lib)
                valid_libraries.append(lib)
            except LibraryValidationException as e:
                log.error(
                    f"Library '{lib['name']}' failed validation and will be skipped: {e}"
                )

        # Filter overlapping libraries
        return self._filter_overlapping_libraries(valid_libraries)

    def validate_library(self, lib: dict[str, Any]):
        structure = lib.get("structure", "")
        if not structure:
            return

        segments = [s for s in structure.split("/") if s]

        has_game_dir = False
        has_game_file = False

        for segment in segments:
            variables_in_segment = re.findall(r"\{[^}]+\}", segment)
            if len(variables_in_segment) > 1:
                raise LibraryValidationException(
                    f"Multiple variables in a single segment: '{segment}'"
                )

            for var in variables_in_segment:
                if var not in VALID_VARIABLES:
                    raise LibraryValidationException(
                        f"Unrecognized variable name: '{var}'"
                    )

                if var == "{gameDir}":
                    has_game_dir = True
                elif var == "{gameFile}":
                    has_game_file = True

        if has_game_dir and has_game_file:
            raise LibraryValidationException(
                "{gameDir} and {gameFile} are mutually exclusive in the same template"
            )

    def _filter_overlapping_libraries(
        self, libraries: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        library_roots = []
        for lib in libraries:
            effective_root = Path(lib["path"])
            structure = lib.get("structure", "")

            if structure:
                segments = [s for s in structure.split("/") if s]
                if segments and not segments[0].startswith("{"):
                    effective_root = effective_root / segments[0]

            library_roots.append(
                {"lib": lib, "effective_root": effective_root.resolve()}
            )

        valid_libraries = []
        for i, lr1 in enumerate(library_roots):
            is_overlap = False
            for j, lr2 in enumerate(library_roots):
                if i == j:
                    continue
                try:
                    lr1["effective_root"].relative_to(lr2["effective_root"])
                    log.error(
                        f"Library '{lr1['lib']['name']}' overlaps with '{lr2['lib']['name']}'. "
                        f"Scan root {lr1['effective_root']} is inside {lr2['effective_root']}. Skipping."
                    )
                    is_overlap = True
                    break
                except ValueError:
                    pass

            if not is_overlap:
                valid_libraries.append(lr1["lib"])

        return valid_libraries

    @staticmethod
    def validate_category(folder_name: str) -> None:
        if folder_name.lower() not in VALID_CATEGORIES:
            log.warning(
                f"Unrecognized {{gameCategory}} folder: '{folder_name}'. "
                f"Expected one of: {', '.join(VALID_CATEGORIES)}."
            )

    @staticmethod
    def match_template(
        base_path: Path, structure: str
    ) -> Generator[dict[str, Any], None, None]:
        """Walk a library's filesystem tree, yielding entries matched against the template.

        Yields dicts with keys: "type", "path", "vars".

        Template mode (structure is non-empty):
            type is one of "gameDir", "gameFile", "biosFile" depending on which
            template variable the entry matched.  vars contains the extracted
            variable values, e.g. {"{platformDir}": "gba", "{gameRegion}": "us"}.

        Flat mode (structure is empty string):
            type is "file" or "dir".  vars is always {}.  The caller (scanner)
            is responsible for resolving the platform from the library's
            per-platform config — flat-mode entries carry no platform context.
        """
        if not structure:
            yield from LibraryHandler._walk_flat(base_path)
            return

        segments = [s for s in structure.split("/") if s]
        yield from LibraryHandler._walk_segments(base_path, segments, {})

    @staticmethod
    def _walk_flat(
        base_path: Path,
    ) -> Generator[dict[str, Any], None, None]:
        if not base_path.exists() or not base_path.is_dir():
            return

        for entry in os.scandir(base_path):
            if entry.name.startswith("."):
                continue

            if entry.is_file():
                yield {"type": "file", "path": Path(entry.path), "vars": {}}
            elif entry.is_dir():
                yield {"type": "dir", "path": Path(entry.path), "vars": {}}

    @staticmethod
    def _collect_bios_files(
        directory: Path, match_vars: dict[str, str]
    ) -> Generator[dict[str, Any], None, None]:
        """Recursively collect all files within a BIOS directory and yield them
        as biosFile entries.  Per spec §5, firmware routing is unconditional when
        the path hint is present — all files resolved through that segment."""
        if not directory.exists() or not directory.is_dir():
            return

        for entry in os.scandir(directory):
            if entry.name.startswith("."):
                continue

            if entry.is_file():
                yield {
                    "type": "biosFile",
                    "path": Path(entry.path),
                    "vars": match_vars,
                }
            elif entry.is_dir():
                yield from LibraryHandler._collect_bios_files(
                    Path(entry.path), match_vars
                )

    @staticmethod
    def _walk_segments(
        current_path: Path,
        segments: list[str],
        current_vars: dict[str, str],
    ) -> Generator[dict[str, Any], None, None]:
        if not current_path.exists() or not current_path.is_dir():
            return

        if not segments:
            return

        segment = segments[0]
        remaining = segments[1:]

        is_game_dir = "{gameDir}" in segment
        is_game_file = "{gameFile}" in segment
        is_platform_bios_hint = "{platformBios}" in segment or segment == "bios"

        for entry in os.scandir(current_path):
            if entry.name.startswith("."):
                continue

            match_vars = current_vars.copy()

            # Literal segment matching (e.g. "roms", "bios")
            if "{" not in segment:
                if entry.name != segment:
                    continue
            else:
                # Variable extraction — one variable per segment (enforced by validation)
                var_match = re.search(r"\{([^}]+)\}", segment)
                if var_match:
                    var_name = var_match.group(1)
                    prefix = segment[: var_match.start()]
                    suffix = segment[var_match.end() :]
                    if entry.name.startswith(prefix) and entry.name.endswith(suffix):
                        val = entry.name[len(prefix) :]
                        if suffix:
                            val = val[: -len(suffix)]
                        match_vars[f"{{{var_name}}}"] = val
                    else:
                        continue

            if is_game_dir and entry.is_dir():
                yield {
                    "type": "gameDir",
                    "path": Path(entry.path),
                    "vars": match_vars,
                }
            elif is_game_file and entry.is_file():
                yield {
                    "type": "gameFile",
                    "path": Path(entry.path),
                    "vars": match_vars,
                }
            elif is_platform_bios_hint:
                if entry.is_file():
                    yield {
                        "type": "biosFile",
                        "path": Path(entry.path),
                        "vars": match_vars,
                    }
                elif entry.is_dir() and not remaining:
                    # Terminal BIOS directory — recursively collect all files
                    yield from LibraryHandler._collect_bios_files(
                        Path(entry.path), match_vars
                    )

            if remaining and entry.is_dir():
                yield from LibraryHandler._walk_segments(
                    Path(entry.path), remaining, match_vars
                )


@dataclass
class ScannedRom:
    """A ROM discovered during a library walk."""
    fs_name: str
    fs_path: str  # Relative to library root
    is_dir: bool  # True for multi-file ROMs (gameDir), False for single-file (gameFile)


@dataclass
class ScannedFirmware:
    """A firmware file discovered during a library walk."""
    file_name: str
    file_path: str  # Relative to library root (directory containing the file)


@dataclass
class PlatformScanEntries:
    """All ROMs and firmware found for a platform within a single library."""
    roms: list[ScannedRom] = field(default_factory=list)
    firmware: list[ScannedFirmware] = field(default_factory=list)


def scan_library(
    library: dict[str, Any],
) -> dict[str, PlatformScanEntries]:
    """Walk a library's filesystem and group entries by platform slug.

    Args:
        library: A library dict from config with keys: id, name, path, structure, platforms.

    Returns:
        A dict mapping platform fs_slug to PlatformScanEntries containing
        the ROMs and firmware found under that platform.

    For template mode, the platform slug is extracted from the {platformDir}
    variable. For flat mode (empty structure), every file/directory at the
    library root is treated as belonging to the platform specified in the
    library's per-platform config (lib["platforms"]). If flat mode has no
    platform config, entries are grouped by directory name as the platform slug.
    """
    lib_path = Path(library["path"])
    structure = library.get("structure", "")
    lib_platforms: dict = library.get("platforms", {})

    result: dict[str, PlatformScanEntries] = {}

    def _ensure_platform(slug: str) -> PlatformScanEntries:
        if slug not in result:
            result[slug] = PlatformScanEntries()
        return result[slug]

    for entry in LibraryHandler.match_template(lib_path, structure):
        entry_type = entry["type"]
        entry_path: Path = entry["path"]
        vars_dict: dict[str, str] = entry["vars"]

        if structure:
            # Template mode — platform comes from {platformDir}
            platform_slug = vars_dict.get("{platformDir}", "")
            if not platform_slug:
                continue

            rel_path = entry_path.relative_to(lib_path)
            platform_entries = _ensure_platform(platform_slug)

            if entry_type == "gameFile":
                platform_entries.roms.append(
                    ScannedRom(
                        fs_name=entry_path.name,
                        fs_path=str(rel_path.parent),
                        is_dir=False,
                    )
                )
            elif entry_type == "gameDir":
                platform_entries.roms.append(
                    ScannedRom(
                        fs_name=entry_path.name,
                        fs_path=str(rel_path.parent),
                        is_dir=True,
                    )
                )
            elif entry_type == "biosFile":
                platform_entries.firmware.append(
                    ScannedFirmware(
                        file_name=entry_path.name,
                        file_path=str(rel_path.parent),
                    )
                )
        else:
            # Flat mode — platform resolution depends on lib["platforms"] config.
            # If the library has a per-platform config, all flat entries belong
            # to that single platform. Otherwise, group by top-level directory.
            if lib_platforms:
                # Use the first (expected: only) platform key from the config
                platform_slug = next(iter(lib_platforms))
            else:
                # No platform config: use the entry's parent directory name as slug
                # (or the entry name itself if it's at the library root)
                try:
                    rel_path = entry_path.relative_to(lib_path)
                    platform_slug = rel_path.parts[0] if rel_path.parts else ""
                except ValueError:
                    continue

            if not platform_slug:
                continue

            rel_path = entry_path.relative_to(lib_path)
            platform_entries = _ensure_platform(platform_slug)

            if entry_type == "file":
                platform_entries.roms.append(
                    ScannedRom(
                        fs_name=entry_path.name,
                        fs_path=str(rel_path.parent),
                        is_dir=False,
                    )
                )
            elif entry_type == "dir":
                platform_entries.roms.append(
                    ScannedRom(
                        fs_name=entry_path.name,
                        fs_path=str(rel_path.parent),
                        is_dir=True,
                    )
                )

    return result
