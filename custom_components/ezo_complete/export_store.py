"""Dated calibration archives + per-device restore pointer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .const import IMPORT_CALIBRATION_SUFFIX


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
