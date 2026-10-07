"""Assemble the small static bundle deployed to Cloudflare Pages."""

from __future__ import annotations

import shutil

from viscount_aligner.paths import AUDIO_ALIGNMENT_PATH, DEPLOY_DIR, HTML_PATH, WEB_DIR

FILES = {
    HTML_PATH: "index.html",
    AUDIO_ALIGNMENT_PATH: "viscount-audio-alignment.json",
    WEB_DIR / "manifest.webmanifest": "manifest.webmanifest",
    WEB_DIR / "app-icon.svg": "app-icon.svg",
    WEB_DIR / "service-worker.js": "service-worker.js",
}

HEADERS = """/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Frame-Options: DENY
  Permissions-Policy: camera=(), microphone=(), geolocation=()

/index.html
  Cache-Control: no-cache

/service-worker.js
  Cache-Control: no-cache
"""

ROUTES = """{
  "version": 1,
  "include": ["/audio/*"],
  "exclude": []
}
"""


def main() -> None:
    """Assemble only the files Pages can host; audio remains in private R2."""
    missing = [source for source in FILES if not source.is_file()]
    if missing:
        names = ", ".join(str(path) for path in missing)
        raise SystemExit(f"Missing required artifact(s): {names}")

    if DEPLOY_DIR.exists():
        shutil.rmtree(DEPLOY_DIR)
    DEPLOY_DIR.mkdir(parents=True)

    for source, destination in FILES.items():
        shutil.copy2(source, DEPLOY_DIR / destination)

    (DEPLOY_DIR / "_headers").write_text(HEADERS, encoding="utf-8")
    (DEPLOY_DIR / "_routes.json").write_text(ROUTES, encoding="utf-8")

    deployed = ", ".join(sorted(path.name for path in DEPLOY_DIR.iterdir()))
    print(f"Cloudflare Pages bundle: {DEPLOY_DIR}")
    print(f"Included: {deployed}")
    print("Audiobook excluded: it is served from the viscount-audio R2 bucket.")


if __name__ == "__main__":
    main()
