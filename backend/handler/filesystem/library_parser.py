import os
import re
from pathlib import Path
from typing import Any, Generator, NamedTuple

from logger.logger import log

VALID_VARIABLES = {
    "{platformDir}",
    "{platformBios}",
    "{gameRegion}",
    "{gameDir}",
    "{gameFile}",
    "{gameCategory}"
}

VALID_CATEGORIES = {
    "retail", "dlc", "hack", "mod", "patch", "update", "demo", "translation", "prototype"
}

class LibraryValidationException(Exception):
    pass

class LibraryParser:
    def __init__(self, libraries: list[dict[str, Any]]):
        self.libraries = libraries

    def get_valid_libraries(self) -> list[dict[str, Any]]:
        valid_libs = []
        for lib in self.libraries:
            try:
                self.validate_library(lib)
                valid_libs.append(lib)
            except LibraryValidationException as e:
                log.error(f"Library '{lib['name']}' failed validation and will be skipped: {e}")
                
        # Filter overlapping libraries
        return self._filter_overlapping_libraries(valid_libs)

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
                raise LibraryValidationException(f"Multiple variables in a single segment: '{segment}'")

            for var in variables_in_segment:
                if var not in VALID_VARIABLES:
                    raise LibraryValidationException(f"Unrecognized variable name: '{var}'")
                
                if var == "{gameDir}":
                    has_game_dir = True
                elif var == "{gameFile}":
                    has_game_file = True

        if has_game_dir and has_game_file:
            raise LibraryValidationException("{gameDir} and {gameFile} are mutually exclusive in the same template")

    def _filter_overlapping_libraries(self, libraries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        library_roots = []
        for lib in libraries:
            effective_root = Path(lib["path"])
            structure = lib.get("structure", "")
            
            if structure:
                segments = [s for s in structure.split("/") if s]
                if segments and not segments[0].startswith("{"):
                    effective_root = effective_root / segments[0]
            
            library_roots.append({
                "lib": lib,
                "effective_root": effective_root.resolve()
            })
            
        valid_libs = []
        for i, lr1 in enumerate(library_roots):
            is_overlap = False
            for j, lr2 in enumerate(library_roots):
                if i == j:
                    continue
                try:
                    lr1["effective_root"].relative_to(lr2["effective_root"])
                    log.error(f"Library '{lr1['lib']['name']}' overlaps with '{lr2['lib']['name']}'. "
                              f"Scan root {lr1['effective_root']} is inside {lr2['effective_root']}. Skipping.")
                    is_overlap = True
                    break
                except ValueError:
                    pass
            
            if not is_overlap:
                valid_libs.append(lr1["lib"])
                
        return valid_libs

    @staticmethod
    def validate_category(folder_name: str) -> None:
        if folder_name.lower() not in VALID_CATEGORIES:
            log.warning(f"Unrecognized {{gameCategory}} folder: '{folder_name}'. "
                        f"Expected one of: {', '.join(VALID_CATEGORIES)}.")

    @staticmethod
    def match_template(base_path: Path, structure: str) -> Generator[dict[str, Any], None, None]:
        if not structure:
            # Flat mode
            yield from LibraryParser._walk_flat(base_path)
            return

        segments = [s for s in structure.split("/") if s]
        yield from LibraryParser._walk_segments(base_path, segments, {})

    @staticmethod
    def _walk_flat(base_path: Path) -> Generator[dict[str, Any], None, None]:
        if not base_path.exists() or not base_path.is_dir():
            return
            
        for entry in os.scandir(base_path):
            if entry.name.startswith("."): continue
            
            # In flat mode, files/folders in base_path are ROMs or BIOS
            # The platform is either implicit from the per-platform override or default
            # Wait, flat mode means the structure is empty, and platform is matched by config mapping.
            # We just yield the raw files and let the caller resolve the platform.
            if entry.is_file():
                yield {"type": "file", "path": Path(entry.path), "vars": {}}
            elif entry.is_dir():
                yield {"type": "dir", "path": Path(entry.path), "vars": {}}

    @staticmethod
    def _walk_segments(current_path: Path, segments: list[str], current_vars: dict[str, str]) -> Generator[dict[str, Any], None, None]:
        if not current_path.exists() or not current_path.is_dir():
            return

        if not segments:
            # We reached the end of the template. 
            # Anything here is a file or dir match based on the last segment type.
            return

        segment = segments[0]
        remaining = segments[1:]

        is_game_dir = "{gameDir}" in segment
        is_game_file = "{gameFile}" in segment
        is_platform_bios_hint = "{platformBios}" in segment or segment == "bios"

        for entry in os.scandir(current_path):
            if entry.name.startswith("."): continue
            
            match_vars = current_vars.copy()

            # Simple template matcher (e.g. "roms", "{platformDir}", "{gameCategory}_games")
            if "{" not in segment:
                if entry.name != segment:
                    continue
            else:
                # We should extract variables. For simplicity, assume one variable per segment (validated).
                var_match = re.search(r"\{([^}]+)\}", segment)
                if var_match:
                    var_name = var_match.group(1)
                    # If the segment has literal parts, strip them
                    prefix = segment[:var_match.start()]
                    suffix = segment[var_match.end():]
                    if entry.name.startswith(prefix) and entry.name.endswith(suffix):
                        val = entry.name[len(prefix):]
                        if suffix:
                            val = val[:-len(suffix)]
                        match_vars[f"{{{var_name}}}"] = val
                    else:
                        continue

            if is_game_dir and entry.is_dir():
                yield {"type": "gameDir", "path": Path(entry.path), "vars": match_vars}
            elif is_game_file and entry.is_file():
                yield {"type": "gameFile", "path": Path(entry.path), "vars": match_vars}
            elif is_platform_bios_hint:
                if entry.is_file():
                    yield {"type": "biosFile", "path": Path(entry.path), "vars": match_vars}
                elif entry.is_dir() and not remaining:
                    # Recursive BIOS collect if it's a dir and template ends here
                    pass # We handle this in the caller or scanner
            
            if remaining and entry.is_dir():
                yield from LibraryParser._walk_segments(Path(entry.path), remaining, match_vars)
