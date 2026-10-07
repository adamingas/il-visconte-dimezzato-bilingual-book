"""Helpers shared by local serving and deployment builds."""

import shutil
from pathlib import Path

from viscount_aligner.paths import SITE_DIR, WEB_ASSETS, WEB_DIR


def sync_web_assets(destination: Path = SITE_DIR) -> None:
    """Copy versioned PWA assets next to the generated reader."""
    destination.mkdir(parents=True, exist_ok=True)
    for name in WEB_ASSETS:
        source = WEB_DIR / name
        if not source.is_file():
            raise FileNotFoundError(f"Missing web asset: {source}")
        shutil.copy2(source, destination / name)
