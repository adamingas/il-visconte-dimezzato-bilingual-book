"""Canonical repository paths.

Everything under ``artifacts/`` is local-only: it contains copyrighted source
books, large media, generated readers, intermediate data, and reports. Keeping
these paths here prevents build and verification commands from drifting apart.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

ARTIFACTS_DIR = ROOT / "artifacts"
SOURCES_DIR = ARTIFACTS_DIR / "sources"
SITE_DIR = ARTIFACTS_DIR / "site"
WORK_DIR = ARTIFACTS_DIR / "work"
REPORTS_DIR = ARTIFACTS_DIR / "reports"
DEPLOY_DIR = ARTIFACTS_DIR / "deploy" / "cloudflare-pages"
WEB_DIR = ROOT / "web"

AUDIO_FILENAME = "il_visconte_dimezzato_EP71iMmmc0Q.webm"
AUDIO_PATH = SITE_DIR / "audio" / AUDIO_FILENAME
ALIGNMENT_PATH = WORK_DIR / "alignment.json"
TRANSCRIPTION_PATH = WORK_DIR / "audio-transcription.json"
AUDIO_ALIGNMENT_PATH = SITE_DIR / "viscount-audio-alignment.json"
HTML_PATH = SITE_DIR / "viscount-bilingual.html"
EPUB_PATH = SITE_DIR / "viscount-bilingual.epub"
TRANSLATION_CACHE_DIR = WORK_DIR / "literal-translations-cache"
SCREENSHOTS_DIR = REPORTS_DIR / "screenshots"

WEB_ASSETS = ("app-icon.svg", "manifest.webmanifest", "service-worker.js")
