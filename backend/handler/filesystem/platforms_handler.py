from config import LIBRARY_BASE_PATH
from config.config_manager import config_manager as cm
from exceptions.fs_exceptions import (
    FolderStructureNotMatchException,
    PlatformAlreadyExistsException,
)

from .base_handler import FSHandler


class FSPlatformsHandler(FSHandler):
    def __init__(self) -> None:
        super().__init__(base_path=LIBRARY_BASE_PATH)

    def _exclude_platforms(self, platforms: list):
        cnfg = cm.get_config()
        return [
            platform
            for platform in platforms
            if platform not in cnfg.EXCLUDED_PLATFORMS
        ]

    def get_platform_fs_structure(self, fs_slug: str) -> str:
        return fs_slug

    async def add_platform(self, fs_slug: str) -> None:
        """Adds platform to the filesystem

        Args:
            fs_slug: platform slug
        """
        try:
            await self.make_directory(fs_slug)
        except FileNotFoundError as e:
            raise PlatformAlreadyExistsException(fs_slug) from e

    async def get_platforms(self) -> list[str]:
        """Retrieves all platforms from the filesystem.

        Returns:
            List of platform slugs.
        """
        try:
            platforms = await self.list_directories(path="")
        except FileNotFoundError as e:
            raise FolderStructureNotMatchException() from e

        return self._exclude_platforms(platforms)
