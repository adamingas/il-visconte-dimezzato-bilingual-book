# Viscount bilingual reader

This repository builds a sentence-aligned Italian–English reader for Italo
Calvino's *Il visconte dimezzato* / *The Cloven Viscount*. It combines selected
Italian and English EPUB editions with the Italian audiobook to produce:

- a responsive, installable web reader with published and literal translations;
- sentence-level audio playback with repeat and speed controls;
- saved browser progress and automatic continuation between segments;
- a native EPUB 3 edition; and
- a Cloudflare Pages bundle whose large audio file is served privately from R2.

The deployed reader is at <https://viscount-433.pages.dev>. The current pipeline
is deliberately book-specific; generalizing source discovery and configuration
is planned separately.

## Repository layout

All local source material and generated output lives below `artifacts/`, which
is ignored by Git because it is copyrighted, large, or reproducible.

| Path | Purpose |
| --- | --- |
| `artifacts/sources/` | Input EPUB editions |
| `artifacts/site/` | Final HTML, EPUB, audio map, and audiobook |
| `artifacts/work/` | Alignment, transcription, model caches, and intermediate data |
| `artifacts/reports/` | Verification screenshots and reports |
| `artifacts/deploy/cloudflare-pages/` | Generated Pages upload bundle |
| `web/` | Versioned manifest, icon, and service worker |
| `viscount_aligner/` | Extraction, alignment, rendering, and shared paths |
| `scripts/` | Pipeline, local server, deployment build, and verification commands |

## Setup

Install Python and Node dependencies:

```bash
uv sync --group dev
npm install
```

Audio processing also requires `ffmpeg` and `ffprobe`. Browser verification uses
Google Chrome. Put the four source EPUBs in `artifacts/sources/` using their
original filenames, and the audiobook at:

```text
artifacts/site/audio/il_visconte_dimezzato_EP71iMmmc0Q.webm
```

## Build

Inspect the EPUBs, build the bilingual alignment, and add audiobook timings:

```bash
uv run python scripts/inspect_sources.py
HF_HOME=$PWD/artifacts/work/huggingface uv run python scripts/build_alignment.py
HF_HOME=$PWD/artifacts/work/huggingface uv run python scripts/transcribe_audio.py
uv run python scripts/build_audio_alignment.py
```

Literal translations are optional and use an OpenAI-compatible model endpoint.
Estimate or run them with `scripts/add_literal_translations.py`; the complete H200
procedure is in [docs/h200-vm-setup.md](docs/h200-vm-setup.md).

Serve the generated reader locally at <http://127.0.0.1:8000>:

```bash
uv run python scripts/serve_reader.py
```

The reader caches its shell automatically and offers an opt-in download of the
149 MB audiobook for offline use. Playback position, selected segment, repeat
count, and speed are stored locally in the browser.

## Verify

```bash
uv run pytest -q
uv run python scripts/verify.py all
npm run test:cloudflare
```

Use `html` or `epub` instead of `all` to run one visual verifier. Screenshots are
written to `artifacts/reports/screenshots/`.

## Deploy to Cloudflare

```bash
npm run build:cloudflare
npm run deploy:cloudflare
```

The Pages project is `viscount`, and its private R2 bucket is `viscount-audio`.
The build excludes the audiobook from Pages and routes `/audio/*` through the
Pages Function to R2. Account setup, local preview, and custom-domain details are
in [docs/cloudflare-deployment.md](docs/cloudflare-deployment.md).

## Notes on the alignment

The pipeline extracts the ten story chapters, segments them with `syntok`, embeds
sentences with a multilingual sentence-transformer, and uses chapter-local
monotonic dynamic programming to align groups of one to three sentences. Tests
check complete, ordered coverage of both books and monotonic audio ranges.

The audiobook transcript is used only as a timing signal: acoustic word anchors
are reconciled with the exact Italian EPUB text so transcription variants do not
replace the published text or accumulate timing drift. Method details are in
[docs/audio-alignment-exploration.md](docs/audio-alignment-exploration.md).

Source books and audio are intentionally not committed. Ensure you have the
right to use and distribute any inputs and generated deployment artifacts.
