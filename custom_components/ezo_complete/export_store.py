"""Dated calibration archives + per-device restore pointer."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re

from .const import IMPORT_CALIBRATION_SUFFIX

_ARCHIVE_PATTERN = re.compile(r"_calibration_(\d{8})-(\d{6})\.txt$")


class ExportStore:
    def __init__(self, folder: Path, slug: str) -> None:
        self._folder = folder
        self._slug = slug.replace("/", "_")

    @property
    def restore_path(self) -> Path:
        return self._folder / f"{self._slug}.{IMPORT_CALIBRATION_SUFFIX}"

    def write(self, payload: str, *, now: datetime) -> tuple[str, str]:
        self._folder.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        archive = self._folder / f"{self._slug}_calibration_{stamp}.txt"
        restore = self.restore_path
        text = payload.rstrip() + "\n"
        archive.write_text(text, encoding="ascii")
        restore.write_text(text, encoding="ascii")
        return str(archive), str(restore)

    def read_restore(self) -> str | None:
        path = self.restore_path
        if not path.is_file():
            return None
        text = path.read_text(encoding="ascii", errors="ignore").strip()
        return text or None

    def get_latest_export_info(self) -> tuple[str | None, datetime | None]:
        """Return (restore_path, export_datetime) from newest archive file.

        Scans for files matching {slug}_calibration_YYYYMMDD-HHMMSS.txt and
        returns info from the most recent one. Returns (None, None) if no
        archives exist.
        """
        if not self._folder.is_dir():
            return None, None
        archives = list(self._folder.glob(f"{self._slug}_calibration_*.txt"))
        if not archives:
            return None, None

        newest: tuple[Path, datetime] | None = None
        for path in archives:
            match = _ARCHIVE_PATTERN.search(path.name)
            if not match:
                continue
            try:
                dt = datetime.strptime(
                    f"{match.group(1)}-{match.group(2)}", "%Y%m%d-%H%M%S"
                ).replace(tzinfo=UTC)
                if newest is None or dt > newest[1]:
                    newest = (path, dt)
            except ValueError:
                continue

        if newest is None:
            return None, None

        restore = self.restore_path
        return str(restore) if restore.is_file() else None, newest[1]
