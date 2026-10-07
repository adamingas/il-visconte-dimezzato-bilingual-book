from __future__ import annotations

import base64
import html
import zipfile
from pathlib import Path
from typing import Mapping

from ebooklib import epub

from viscount_aligner.alignment import AlignmentUnit
from viscount_aligner.sources import SourceSpec


def _cover_asset(source: SourceSpec) -> tuple[str, bytes] | None:
    with zipfile.ZipFile(source.path) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if name.lower().endswith(("cover.jpg", "cover.jpeg", "cover.png"))
        ]
        if not candidates:
            return None
        name = min(candidates, key=lambda value: ("images/cover" not in value.lower(), len(value)))
        mime = "image/png" if name.lower().endswith(".png") else "image/jpeg"
        return mime, archive.read(name)


def _cover_data_uri(source: SourceSpec) -> str:
    asset = _cover_asset(source)
    if asset is None:
        return ""
    mime, content = asset
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _sentence_lines(sentences: tuple) -> str:
    return "".join(f"<p>{html.escape(sentence.text)}</p>" for sentence in sentences)


def _unit_html(
    unit: AlignmentUnit,
    literal_translations: Mapping[str, str] | None = None,
) -> str:
    badge = ""
    if unit.confidence == "supplemental":
        badge = (
            '<span class="supplement" title="English text supplied because both '
            'provided English editions omit this line">Supplement</span>'
        )
    literal_lines = (
        [literal_translations[sentence.id] for sentence in unit.italian]
        if literal_translations is not None
        else []
    )
    search_text = " ".join(
        [*(sentence.text for sentence in (*unit.italian, *unit.english)), *literal_lines]
    )
    row_number = unit.id.split("-a")[-1].lstrip("0") or "0"
    return f"""
<article class="alignment-row" id="{unit.id}" data-chapter="{unit.chapter}"
  data-search="{html.escape(search_text, quote=True)}">
  <div class="row-number">
    <button class="row-selector" type="button" data-select-section="{unit.id}"
      aria-label="Select section {row_number} for audiobook playback"
      title="Select this section for playback" disabled>
      <span>{row_number}</span><span class="row-play-icon" aria-hidden="true">▶</span>
    </button>
    {badge}
  </div>
  <div class="sentence-cell italian" lang="it">{_sentence_lines(unit.italian)}</div>
  <div class="sentence-cell english translation-published" lang="en">{_sentence_lines(unit.english)}</div>
  {f'<div class="sentence-cell english translation-literal" lang="en">{''.join(f"<p>{html.escape(line)}</p>" for line in literal_lines)}</div>' if literal_lines else ''}
</article>"""


def render_html(
    units: tuple[AlignmentUnit, ...],
    italian_source: SourceSpec,
    english_source: SourceSpec,
    destination: Path,
    literal_translations: Mapping[str, str] | None = None,
) -> None:
    chapters: list[str] = []
    for chapter_number in range(1, 11):
        rows = "\n".join(
            _unit_html(unit, literal_translations)
            for unit in units
            if unit.chapter == chapter_number
        )
        chapters.append(
            f"""
<section class="chapter" id="chapter-{chapter_number}" data-chapter-section="{chapter_number}">
  <h2><span lang="it">Capitolo {chapter_number}</span><span lang="en">Chapter {chapter_number}</span></h2>
  {rows}
</section>"""
        )

    cover = _cover_data_uri(italian_source)
    cover_html = (
        f'<img class="cover" src="{cover}" alt="Il visconte dimezzato cover">'
        if cover
        else ""
    )
    chapter_options = "".join(
        f'<option value="{number}">Chapter {number}</option>' for number in range(1, 11)
    )
    translation_controls = (
        """
    <div class="translation-controls" aria-label="English translation">
      <button type="button" data-translation="published" aria-pressed="true">Published</button>
      <button type="button" data-translation="literal" aria-pressed="false">Literal</button>
    </div>"""
        if literal_translations is not None
        else ""
    )
    translation_heading = (
        'English · <span id="translation-label">Published</span>'
        if literal_translations is not None
        else "English"
    )
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#25313a">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="app-icon.svg" type="image/svg+xml">
<title>Il visconte dimezzato · The Cloven Viscount</title>
<style>
:root {{
  color-scheme: light;
  --paper: #fbfaf7;
  --paper-strong: #ffffff;
  --ink: #242321;
  --muted: #6d6962;
  --line: #d8d4cc;
  --line-soft: #e9e6df;
  --italian: #176c54;
  --english: #9a3e38;
  --toolbar: #25313a;
  --toolbar-ink: #f7f5ef;
  --reader-size: 18px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; scroll-padding-top: 154px; }}
body {{
  margin: 0;
  padding-bottom: calc(136px + env(safe-area-inset-bottom));
  background: var(--paper);
  color: var(--ink);
  font-family: Georgia, "Times New Roman", serif;
}}
button, input, select {{ font: inherit; }}
button, select {{ cursor: pointer; }}
.app-header {{
  position: sticky;
  top: 0;
  z-index: 20;
  box-shadow: 0 1px 0 rgba(0, 0, 0, .16);
}}
.identity {{
  min-height: 68px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px max(16px, calc((100vw - 1280px) / 2));
  background: var(--paper-strong);
}}
.cover {{
  width: 38px;
  height: 52px;
  object-fit: cover;
  border: 1px solid var(--line);
}}
.identity-text {{ min-width: 0; }}
h1 {{
  margin: 0;
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: 0;
}}
.byline {{
  margin: 2px 0 0;
  color: var(--muted);
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 12px;
}}
.menu-button, .drawer-head, .menu-backdrop {{ display: none; }}
.toolbar {{
  min-height: 52px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px max(16px, calc((100vw - 1280px) / 2));
  background: var(--toolbar);
  color: var(--toolbar-ink);
  font-family: ui-sans-serif, system-ui, sans-serif;
}}
.toolbar select, .toolbar input, .toolbar button {{
  min-height: 36px;
  border: 1px solid #5a6670;
  border-radius: 4px;
  background: #ffffff;
  color: #20272c;
}}
.toolbar select {{ width: 130px; padding: 0 30px 0 10px; }}
.search {{ flex: 1; min-width: 120px; max-width: 440px; padding: 0 11px; }}
.type-controls, .language-controls, .translation-controls {{ display: flex; }}
.type-controls button, .language-controls button, .translation-controls button {{
  width: 40px;
  padding: 0;
  font-weight: 700;
}}
.type-controls button + button, .language-controls button + button, .translation-controls button + button {{
  margin-left: -1px;
  border-top-left-radius: 0;
  border-bottom-left-radius: 0;
}}
.type-controls button:first-child, .language-controls button:first-child, .translation-controls button:first-child {{
  border-top-right-radius: 0;
  border-bottom-right-radius: 0;
}}
.language-controls {{ display: none; }}
.language-controls button[aria-pressed="true"] {{
  background: #dce8e3;
  color: #174b3c;
}}
.translation-controls button {{ width: auto; padding: 0 10px; font-size: 12px; }}
.translation-controls button[aria-pressed="true"] {{
  background: #f1e1df;
  color: #74312d;
}}
.column-headings {{
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) minmax(0, 1fr);
  max-width: 1280px;
  margin: 0 auto;
  border-bottom: 2px solid var(--line);
  background: var(--paper);
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 12px;
  font-weight: 800;
  text-transform: uppercase;
}}
.column-headings span {{ padding: 10px 18px; }}
.column-headings .it-label {{ color: var(--italian); }}
.column-headings .en-label {{ color: var(--english); border-left: 1px solid var(--line); }}
main {{ max-width: 1280px; margin: 0 auto; }}
.chapter {{ border-bottom: 1px solid var(--line); }}
.chapter h2 {{
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) minmax(0, 1fr);
  margin: 0;
  padding: 30px 0 10px;
  border-bottom: 1px solid var(--line);
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 14px;
  letter-spacing: 0;
  text-transform: uppercase;
}}
.chapter h2 span:first-child {{ grid-column: 2; color: var(--italian); padding: 0 18px; }}
.chapter h2 span:last-child {{ color: var(--english); padding: 0 18px; }}
.alignment-row {{
  display: grid;
  grid-template-columns: 58px minmax(0, 1fr) minmax(0, 1fr);
  border-bottom: 1px solid var(--line-soft);
  background: var(--paper-strong);
}}
.alignment-row:nth-of-type(even) {{ background: #f6f5f1; }}
.alignment-row:target {{ box-shadow: inset 4px 0 0 #d3a52b; }}
.alignment-row.is-current {{
  position: relative;
  z-index: 1;
  background: #edf5f0;
  box-shadow: inset 4px 0 0 #8fb7a8, 0 1px 7px rgba(35, 77, 62, .08);
}}
.alignment-row.is-current .row-number {{ color: var(--italian); font-weight: 800; }}
.row-number {{
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  padding: 14px 6px;
  color: var(--muted);
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 10px;
  text-align: center;
}}
.row-selector {{
  width: 42px;
  min-height: 42px;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  padding: 3px;
  border: 1px solid transparent;
  border-radius: 11px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}}
.row-play-icon {{
  color: var(--italian);
  font-size: 8px;
  line-height: 9px;
  opacity: .28;
}}
.row-selector:hover:not(:disabled),
.row-selector:focus-visible {{
  border-color: #aac5ba;
  background: #f1f7f4;
}}
.row-selector:focus-visible {{ outline: 2px solid var(--italian); outline-offset: 2px; }}
.row-selector:disabled {{ cursor: default; opacity: .55; }}
.alignment-row.is-current .row-selector {{
  border-color: #8fb7a8;
  background: #deeee7;
}}
.alignment-row.is-current .row-play-icon,
.row-selector:hover .row-play-icon,
.row-selector:focus-visible .row-play-icon {{ opacity: 1; }}
@media (hover: none) {{ .row-play-icon {{ opacity: .62; }} }}
.offline-control {{ display: flex; align-items: center; gap: 8px; }}
.toolbar .offline-button {{
  width: auto;
  padding: 0 11px;
  white-space: nowrap;
}}
.offline-prompt {{
  position: fixed;
  right: 16px;
  bottom: calc(136px + env(safe-area-inset-bottom));
  z-index: 50;
  width: min(420px, calc(100vw - 32px));
  padding: 16px;
  border: 1px solid #8d999f;
  border-radius: 9px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, .25);
  background: var(--toolbar);
  color: var(--toolbar-ink);
  font-family: ui-sans-serif, system-ui, sans-serif;
}}
.offline-prompt p {{ margin: 0 0 12px; font-size: 14px; line-height: 1.4; }}
.offline-prompt-actions {{ display: flex; justify-content: flex-end; gap: 8px; }}
.offline-prompt button {{
  min-height: 40px;
  padding: 0 13px;
  border: 1px solid #819099;
  border-radius: 5px;
}}
.offline-prompt .save-audio {{
  border-color: #ffffff;
  background: #ffffff;
  color: #20272c;
  font-weight: 700;
}}
.player-dock {{
  position: fixed;
  left: 50%;
  bottom: max(12px, env(safe-area-inset-bottom));
  z-index: 30;
  width: min(410px, calc(100vw - 20px));
  padding: 9px 12px 11px;
  border: 1px solid rgba(255, 255, 255, .16);
  border-radius: 22px;
  box-shadow: 0 14px 42px rgba(24, 30, 33, .28);
  transform: translateX(-50%);
  background: rgba(37, 49, 58, .97);
  color: var(--toolbar-ink);
  font-family: ui-sans-serif, system-ui, sans-serif;
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
}}
.player-status {{
  min-height: 18px;
  margin: 0 0 7px;
  overflow: hidden;
  color: #d9ddd9;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
  text-overflow: ellipsis;
  white-space: nowrap;
}}
.player-controls {{
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
}}
.player-control {{
  width: 44px;
  height: 44px;
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid #59646a;
  border-radius: 50%;
  background: #354149;
  color: #f7f6f1;
  cursor: pointer;
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 21px;
  line-height: 1;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}}
.player-control:hover:not(:disabled),
.player-control:focus-visible {{ background: #46545c; }}
.player-control:focus-visible {{ outline: 3px solid #a9cfbf; outline-offset: 2px; }}
.player-control:disabled {{ cursor: default; opacity: .38; }}
.player-play {{
  width: 58px;
  height: 58px;
  border-color: #58a286;
  background: var(--italian);
  box-shadow: 0 4px 12px rgba(0, 0, 0, .24);
  font-size: 22px;
}}
.player-play:hover:not(:disabled),
.player-play:focus-visible {{ background: #1d8064; }}
.player-play[data-playing="false"] {{ padding-left: 3px; }}
.player-pill {{
  width: 54px;
  border-radius: 15px;
  flex-direction: column;
  gap: 1px;
  font-size: 14px;
  font-weight: 800;
}}
.player-pill small {{
  color: #bec5c2;
  font-size: 7px;
  font-weight: 650;
  letter-spacing: .04em;
  text-transform: uppercase;
}}
.player-center {{ font-size: 23px; }}
.speed-panel {{
  position: absolute;
  left: 50%;
  bottom: calc(100% + 10px);
  width: min(350px, calc(100vw - 20px));
  padding: 14px 16px 12px;
  border: 1px solid #778188;
  border-radius: 16px;
  box-shadow: 0 12px 35px rgba(20, 25, 28, .28);
  transform: translateX(-50%);
  background: #2f3b43;
  color: var(--toolbar-ink);
}}
.speed-panel-head {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 7px;
  font-size: 12px;
  font-weight: 750;
}}
.speed-panel output {{ color: #b9dbcD; font-size: 14px; }}
.speed-slider {{
  width: 100%;
  height: 32px;
  margin: 0;
  accent-color: #72b59b;
  cursor: pointer;
}}
.speed-labels {{
  display: flex;
  justify-content: space-between;
  margin: -2px 2px 0;
  color: #bfc6c3;
  font-size: 9px;
}}
.speed-hint {{
  margin: 7px 0 0;
  color: #aeb7b4;
  font-size: 9px;
  line-height: 1.3;
  text-align: center;
}}
.visually-hidden {{
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}}
.supplement {{
  display: block;
  margin-top: 7px;
  color: #7c5400;
  font-size: 8px;
  font-weight: 800;
  line-height: 1.2;
  text-transform: uppercase;
  overflow-wrap: anywhere;
}}
.sentence-cell {{
  min-width: 0;
  padding: 15px 18px 17px;
  font-size: var(--reader-size);
  line-height: 1.58;
  overflow-wrap: anywhere;
}}
.sentence-cell.english {{ border-left: 1px solid var(--line); }}
.translation-literal {{ display: none; }}
body[data-translation="literal"] .translation-published {{ display: none; }}
body[data-translation="literal"] .translation-literal {{ display: block; }}
.sentence-cell p {{ margin: 0; }}
.sentence-cell p + p {{ margin-top: .65em; }}
.no-results {{
  display: none;
  padding: 64px 20px;
  color: var(--muted);
  font-family: ui-sans-serif, system-ui, sans-serif;
  text-align: center;
}}
.no-results.visible {{ display: block; }}
footer {{
  padding: 32px 18px 48px;
  color: var(--muted);
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-size: 11px;
  line-height: 1.5;
  text-align: center;
}}
[hidden] {{ display: none !important; }}
@media (max-width: 720px) {{
  html {{ scroll-padding-top: 64px; }}
  body[data-menu-open="true"] {{ overflow: hidden; }}
  .identity {{ min-height: 54px; gap: 9px; padding: 6px 12px; }}
  .cover {{ width: 28px; height: 38px; }}
  .identity-text {{ flex: 1; }}
  h1 {{
    overflow: hidden;
    font-size: 15px;
    line-height: 1.2;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  .title-separator, .english-title, .byline {{ display: none; }}
  .menu-button {{
    width: 42px;
    height: 42px;
    display: inline-flex;
    flex: 0 0 42px;
    align-items: center;
    justify-content: center;
    border: 0;
    background: transparent;
    color: var(--ink);
    font-family: ui-sans-serif, system-ui, sans-serif;
    font-size: 25px;
    line-height: 1;
  }}
  .toolbar {{
    position: fixed;
    top: 0;
    right: 0;
    z-index: 42;
    width: min(320px, 86vw);
    height: 100dvh;
    min-height: 0;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 14px;
    padding: 0 18px 24px;
    overflow-y: auto;
    box-shadow: -10px 0 30px rgba(0, 0, 0, .24);
    transform: translateX(105%);
    visibility: hidden;
    transition: transform 180ms ease, visibility 180ms;
  }}
  body[data-menu-open="true"] .toolbar {{
    transform: translateX(0);
    visibility: visible;
  }}
  .drawer-head {{
    min-height: 62px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid #56626b;
    font-family: ui-sans-serif, system-ui, sans-serif;
    font-size: 15px;
    font-weight: 750;
  }}
  .toolbar .drawer-close {{
    width: 42px;
    min-height: 42px;
    border: 0;
    background: transparent;
    color: var(--toolbar-ink);
    font-size: 28px;
    line-height: 1;
  }}
  .toolbar select, .search {{ width: 100%; max-width: none; flex: 0 0 auto; }}
  .offline-control {{ width: 100%; }}
  .toolbar .offline-button {{ width: 100%; }}
  .type-controls, .language-controls, .translation-controls {{ align-self: flex-start; }}
  .type-controls button, .language-controls button {{ width: 48px; }}
  .translation-controls button {{ min-width: 82px; }}
  .language-controls {{ display: flex; }}
  .menu-backdrop {{
    position: fixed;
    inset: 0;
    z-index: 41;
    display: block;
    border: 0;
    background: rgba(22, 25, 27, .48);
    opacity: 0;
    visibility: hidden;
    transition: opacity 180ms ease, visibility 180ms;
  }}
  body[data-menu-open="true"] .menu-backdrop {{ opacity: 1; visibility: visible; }}
  .column-headings {{ display: none; }}
  .chapter h2 {{ grid-template-columns: 50px 1fr; padding-top: 25px; }}
  .chapter h2 span:first-child {{ grid-column: 2; padding: 0 13px; }}
  .chapter h2 span:last-child {{ grid-column: 2; padding: 3px 13px 0; }}
  .alignment-row {{ grid-template-columns: 50px minmax(0, 1fr); }}
  .row-number {{ grid-row: 1 / span 2; padding: 12px 4px; }}
  .sentence-cell {{ padding: 12px 13px 14px; }}
  .sentence-cell.english {{
    grid-column: 2;
    border-top: 1px dashed var(--line);
    border-left: 0;
    color: #383431;
  }}
  body[data-language="it"] .sentence-cell.english,
  body[data-language="it"] .chapter h2 span:last-child {{ display: none; }}
  body[data-language="en"] .sentence-cell.italian,
  body[data-language="en"] .chapter h2 span:first-child {{ display: none; }}
  .player-dock {{ border-radius: 20px; }}
  .offline-prompt {{ right: 10px; width: calc(100vw - 20px); }}
}}
@media (max-width: 360px) {{
  .player-dock {{ padding-right: 8px; padding-left: 8px; }}
  .player-controls {{ gap: 3px; }}
  .player-control {{ width: 38px; height: 38px; font-size: 19px; }}
  .player-play {{ width: 50px; height: 50px; font-size: 20px; }}
  .player-pill {{ width: 47px; font-size: 12px; }}
  .player-pill small {{ font-size: 6px; }}
}}
@media print {{
  .app-header {{ position: static; }}
  .toolbar, .menu-button, .menu-backdrop, .offline-prompt, .player-dock {{ display: none; }}
  html {{ scroll-padding-top: 0; }}
  body {{ padding-bottom: 0; }}
  .alignment-row {{ break-inside: avoid; }}
  .sentence-cell {{ font-size: 11pt; }}
}}
</style>
</head>
<body data-language="both" data-translation="published" data-menu-open="false">
<header class="app-header">
  <div class="identity">
    {cover_html}
    <div class="identity-text">
      <h1><span lang="it">Il visconte dimezzato</span><span class="title-separator"> · </span><span class="english-title" lang="en">The Cloven Viscount</span></h1>
      <p class="byline">Italo Calvino · Italian / English parallel text</p>
    </div>
    <button id="menu-toggle" class="menu-button" type="button" aria-label="Open reader menu" aria-controls="reader-tools" aria-expanded="false">☰</button>
  </div>
  <div id="reader-tools" class="toolbar" role="toolbar" aria-label="Reader controls">
    <div class="drawer-head"><span>Reader controls</span><button id="menu-close" class="drawer-close" type="button" aria-label="Close reader menu">×</button></div>
    <select id="chapter-select" aria-label="Go to chapter">
      <option value="">All chapters</option>{chapter_options}
    </select>
    <input id="search" class="search" type="search" placeholder="Search both languages" aria-label="Search both languages">
    <div class="type-controls" aria-label="Text size">
      <button id="type-down" type="button" title="Decrease text size" aria-label="Decrease text size">A−</button>
      <button id="type-up" type="button" title="Increase text size" aria-label="Increase text size">A+</button>
    </div>
    <div class="language-controls" aria-label="Language view">
      <button type="button" data-language="both" aria-pressed="true">Both</button>
      <button type="button" data-language="it" aria-pressed="false">IT</button>
      <button type="button" data-language="en" aria-pressed="false">EN</button>
    </div>
    {translation_controls}
    <div class="offline-control">
      <button id="offline-audio" class="offline-button" type="button" disabled>Checking offline audio…</button>
      <span id="audio-status" class="visually-hidden" role="status" aria-live="polite"></span>
    </div>
  </div>
  <button id="menu-backdrop" class="menu-backdrop" type="button" aria-label="Close reader menu"></button>
  <div class="column-headings" aria-hidden="true">
    <span></span><span class="it-label">Italiano</span><span class="en-label">{translation_heading}</span>
  </div>
</header>
<main id="reader">
  {''.join(chapters)}
  <p id="no-results" class="no-results">No matching sentences</p>
</main>
<div id="player-dock" class="player-dock" role="region" aria-label="Audiobook controls">
  <div id="speed-panel" class="speed-panel" hidden>
    <div class="speed-panel-head">
      <span>Playback speed</span>
      <output id="speed-output" for="speed-slider">1×</output>
    </div>
    <input id="speed-slider" class="speed-slider" type="range" min="0.5" max="1.2"
      step="0.01" value="1" list="speed-anchors" aria-label="Playback speed">
    <datalist id="speed-anchors">
      <option value="0.5"></option><option value="0.7"></option>
      <option value="0.9"></option><option value="1"></option>
      <option value="1.2"></option>
    </datalist>
    <div class="speed-labels" aria-hidden="true">
      <span>0.5</span><span>0.7</span><span>0.9</span><span>1</span><span>1.2</span>
    </div>
    <p class="speed-hint">Continuous adjustment · settles onto a marker when released nearby</p>
  </div>
  <p id="player-status" class="player-status" aria-live="polite">Loading timestamps…</p>
  <div class="player-controls">
    <button id="previous-segment" class="player-control" type="button"
      aria-label="Previous section" title="Previous section" disabled>←</button>
    <button id="play-segment" class="player-control player-play" type="button"
      aria-label="Play current section" title="Play current section"
      data-playing="false" disabled>▶</button>
    <button id="next-segment" class="player-control" type="button"
      aria-label="Next section" title="Next section" disabled>→</button>
    <button id="repeat-segment" class="player-control player-pill" type="button"
      aria-label="Repeat current section zero times" title="Change repeat count" disabled>
      <span id="repeat-count">0×</span><small>repeat</small>
    </button>
    <button id="speed-toggle" class="player-control player-pill" type="button"
      aria-label="Playback speed 1 times" aria-controls="speed-panel" aria-expanded="false"
      title="Change playback speed" disabled>
      <span id="speed-button-value">1×</span><small>speed</small>
    </button>
    <button id="center-segment" class="player-control player-center" type="button"
      aria-label="Center current text" title="Center current text" disabled>◎</button>
  </div>
</div>
<audio id="narration" preload="metadata"></audio>
<aside id="offline-prompt" class="offline-prompt" aria-label="Offline audiobook" hidden>
  <p>Save the 149 MB Italian audiobook on this device for listening without a connection?</p>
  <div class="offline-prompt-actions">
    <button id="dismiss-offline" type="button">Not now</button>
    <button id="save-audio" class="save-audio" type="button">Save audiobook</button>
  </div>
</aside>
<footer>
  Italian source: {html.escape(italian_source.edition)} · English source: {html.escape(english_source.edition)}
</footer>
<script>
const root = document.documentElement;
const search = document.querySelector('#search');
const rows = [...document.querySelectorAll('.alignment-row')];
const sections = [...document.querySelectorAll('[data-chapter-section]')];
const noResults = document.querySelector('#no-results');
const player = document.querySelector('#narration');
const playerDock = document.querySelector('#player-dock');
const playerStatus = document.querySelector('#player-status');
const previousSegment = document.querySelector('#previous-segment');
const playSegmentButton = document.querySelector('#play-segment');
const nextSegment = document.querySelector('#next-segment');
const repeatSegment = document.querySelector('#repeat-segment');
const repeatCount = document.querySelector('#repeat-count');
const centerSegment = document.querySelector('#center-segment');
const speedToggle = document.querySelector('#speed-toggle');
const speedPanel = document.querySelector('#speed-panel');
const speedSlider = document.querySelector('#speed-slider');
const speedOutput = document.querySelector('#speed-output');
const speedButtonValue = document.querySelector('#speed-button-value');
const offlineButton = document.querySelector('#offline-audio');
const offlinePrompt = document.querySelector('#offline-prompt');
const audioStatus = document.querySelector('#audio-status');
const AUDIO_URL = new URL('./audio/il_visconte_dimezzato_EP71iMmmc0Q.webm?v=2', document.baseURI).href;
const AUDIO_MAP_URL = new URL('./viscount-audio-alignment.json', document.baseURI).href;
const AUDIO_CACHE = 'viscount-audio-v2';
const AUDIO_PROGRESS_KEY = 'viscount-audio-progress-v1';
const REPEAT_KEY = 'viscount-repeat-count';
const REPEAT_OPTIONS = [0, 3, 5, 8];
const SPEED_ANCHORS = [0.5, 0.7, 0.9, 1, 1.2];
const normalize = value => value.normalize('NFD').replace(/\\p{{Diacritic}}/gu, '').toLocaleLowerCase();
const menuToggle = document.querySelector('#menu-toggle');
const closeMenu = () => {{
  document.body.dataset.menuOpen = 'false';
  menuToggle.setAttribute('aria-expanded', 'false');
}};
const openMenu = () => {{
  document.body.dataset.menuOpen = 'true';
  menuToggle.setAttribute('aria-expanded', 'true');
}};
menuToggle.addEventListener('click', openMenu);
document.querySelector('#menu-close').addEventListener('click', closeMenu);
document.querySelector('#menu-backdrop').addEventListener('click', closeMenu);
document.addEventListener('keydown', event => {{
  if (event.key === 'Escape') {{
    closeMenu();
    setSpeedPanel(false);
  }}
}});

document.querySelector('#chapter-select').addEventListener('change', event => {{
  if (event.target.value) document.querySelector(`#chapter-${{event.target.value}}`).scrollIntoView();
  else window.scrollTo({{ top: 0, behavior: 'smooth' }});
  if (matchMedia('(max-width: 720px)').matches) closeMenu();
}});

search.addEventListener('input', () => {{
  const query = normalize(search.value.trim());
  let visible = 0;
  rows.forEach(row => {{
    const match = !query || normalize(row.dataset.search).includes(query);
    row.hidden = !match;
    if (match) visible += 1;
  }});
  sections.forEach(section => {{
    section.hidden = ![...section.querySelectorAll('.alignment-row')].some(row => !row.hidden);
  }});
  noResults.classList.toggle('visible', visible === 0);
}});

let readerSize = Number(localStorage.getItem('viscount-reader-size')) || 18;
const setReaderSize = value => {{
  readerSize = Math.max(15, Math.min(24, value));
  root.style.setProperty('--reader-size', `${{readerSize}}px`);
  localStorage.setItem('viscount-reader-size', readerSize);
}};
setReaderSize(readerSize);
document.querySelector('#type-down').addEventListener('click', () => setReaderSize(readerSize - 1));
document.querySelector('#type-up').addEventListener('click', () => setReaderSize(readerSize + 1));

document.querySelectorAll('.language-controls [data-language]').forEach(button => {{
  button.addEventListener('click', () => {{
    document.body.dataset.language = button.dataset.language;
    document.querySelectorAll('.language-controls [data-language]').forEach(candidate => {{
      candidate.setAttribute('aria-pressed', String(candidate === button));
    }});
  }});
}});

const translationLabel = document.querySelector('#translation-label');
const savedTranslation = localStorage.getItem('viscount-english-translation');
const setTranslation = value => {{
  if (!document.querySelector(`.translation-controls [data-translation="${{value}}"]`)) return;
  document.body.dataset.translation = value;
  localStorage.setItem('viscount-english-translation', value);
  if (translationLabel) translationLabel.textContent = value === 'literal' ? 'Literal' : 'Published';
  document.querySelectorAll('.translation-controls [data-translation]').forEach(candidate => {{
    candidate.setAttribute('aria-pressed', String(candidate.dataset.translation === value));
  }});
}};
document.querySelectorAll('.translation-controls [data-translation]').forEach(button => {{
  button.addEventListener('click', () => setTranslation(button.dataset.translation));
}});
if (savedTranslation) setTranslation(savedTranslation);

let audioUnits = [];
let currentIndex = 0;
let repeatIndex = 0;
let completedRepeats = 0;
let segmentMonitor = null;
let audioObjectUrl = null;
let loadingAudio = false;
let handlingSegmentEnd = false;
let playbackVersion = 0;
let pendingResumeTime = null;
let lastSavedProgressSecond = null;

const announceAudio = message => {{ audioStatus.textContent = message; }};
const currentUnit = () => audioUnits[currentIndex] || null;
const currentRow = () => currentUnit()?.row || null;
const isPlaying = () => !player.paused && !player.ended;
const totalPlays = () => REPEAT_OPTIONS[repeatIndex] || 1;
const formatSpeed = value => `${{Number(Number(value).toFixed(2))}}×`;

const savedRepeat = Number.parseInt(localStorage.getItem(REPEAT_KEY), 10);
const savedRepeatIndex = REPEAT_OPTIONS.indexOf(savedRepeat);
if (savedRepeatIndex >= 0) repeatIndex = savedRepeatIndex;

const updateRepeatControl = ({{ persist = false }} = {{}}) => {{
  const repeats = REPEAT_OPTIONS[repeatIndex];
  repeatCount.textContent = `${{repeats}}×`;
  repeatSegment.setAttribute('aria-label', `Repeat each section ${{repeats}} times`);
  if (persist) localStorage.setItem(REPEAT_KEY, String(repeats));
}};
updateRepeatControl();

const readSavedProgress = () => {{
  try {{
    const value = JSON.parse(localStorage.getItem(AUDIO_PROGRESS_KEY));
    if (!value || typeof value.unitId !== 'string') return null;
    return value;
  }} catch {{
    return null;
  }}
}};

const saveProgress = (time = player.currentTime) => {{
  const unit = currentUnit();
  if (!unit) return;
  const start = Number(unit.audio.start);
  const end = Number(unit.audio.end);
  const candidate = Number(time);
  const safeTime = Number.isFinite(candidate) ? Math.max(start, Math.min(end, candidate)) : start;
  localStorage.setItem(AUDIO_PROGRESS_KEY, JSON.stringify({{
    unitId: unit.id,
    time: Number(safeTime.toFixed(3)),
    updatedAt: new Date().toISOString(),
  }}));
}};

const canResumeCurrent = () => {{
  const unit = currentUnit();
  if (!unit) return false;
  const time = pendingResumeTime ?? player.currentTime;
  return Number.isFinite(time)
    && time >= Number(unit.audio.start)
    && time < Number(unit.audio.end) - 0.025;
}};

let playbackRate = Number.parseFloat(localStorage.getItem('viscount-playback-rate'));
if (!Number.isFinite(playbackRate) || playbackRate < 0.5 || playbackRate > 1.2) playbackRate = 1;

const setPlaybackRate = (value, {{ persist = false }} = {{}}) => {{
  playbackRate = Math.max(0.5, Math.min(1.2, Number(value)));
  player.defaultPlaybackRate = playbackRate;
  player.playbackRate = playbackRate;
  speedSlider.value = String(playbackRate);
  const label = formatSpeed(playbackRate);
  speedOutput.value = label;
  speedOutput.textContent = label;
  speedButtonValue.textContent = label;
  speedToggle.setAttribute('aria-label', `Playback speed ${{playbackRate}} times`);
  if (persist) localStorage.setItem('viscount-playback-rate', String(playbackRate));
}};
setPlaybackRate(playbackRate);

let restoreOfflinePromptAfterSpeed = false;
const setSpeedPanel = open => {{
  if (open && !offlinePrompt.hidden) {{
    offlinePrompt.hidden = true;
    restoreOfflinePromptAfterSpeed = true;
  }} else if (!open && restoreOfflinePromptAfterSpeed) {{
    offlinePrompt.hidden = false;
    restoreOfflinePromptAfterSpeed = false;
  }}
  speedPanel.hidden = !open;
  speedToggle.setAttribute('aria-expanded', String(open));
  if (open) speedSlider.focus();
}};

speedToggle.addEventListener('click', () => setSpeedPanel(speedPanel.hidden));
speedSlider.addEventListener('input', () => setPlaybackRate(Number(speedSlider.value)));
speedSlider.addEventListener('change', () => {{
  const raw = Number(speedSlider.value);
  const nearest = SPEED_ANCHORS.reduce((best, anchor) =>
    Math.abs(anchor - raw) < Math.abs(best - raw) ? anchor : best,
  );
  setPlaybackRate(Math.abs(nearest - raw) <= 0.035 ? nearest : raw, {{ persist: true }});
}});
document.addEventListener('click', event => {{
  if (
    !speedPanel.hidden &&
    !speedPanel.contains(event.target) &&
    !speedToggle.contains(event.target)
  ) setSpeedPanel(false);
}});

const updateStatus = () => {{
  const unit = currentUnit();
  if (!unit) return;
  const position = `Section ${{currentIndex + 1}} of ${{audioUnits.length}}`;
  const range = `${{unit.audio.start_timestamp}}–${{unit.audio.end_timestamp}}`;
  playerStatus.textContent = isPlaying()
    ? `${{position}} · play ${{completedRepeats + 1}} of ${{totalPlays()}} · ${{range}}`
    : `${{position}} · ${{range}}`;
}};

const setPlayingUI = playing => {{
  playSegmentButton.dataset.playing = String(playing);
  playSegmentButton.textContent = playing ? 'Ⅱ' : '▶';
  playSegmentButton.setAttribute('aria-label', playing ? 'Pause current section' : 'Play current section');
  playSegmentButton.title = playing ? 'Pause current section' : 'Play current section';
  updateStatus();
}};

const centerCurrent = () => {{
  const row = currentRow();
  if (!row || row.hidden) return;
  const headerHeight = document.querySelector('.app-header').getBoundingClientRect().height;
  const dockHeight = playerDock.getBoundingClientRect().height;
  const rowTop = row.getBoundingClientRect().top + window.scrollY;
  const availableHeight = window.innerHeight - headerHeight - dockHeight - 24;
  const centeredOffset = Math.max(12, (availableHeight - row.offsetHeight) / 2);
  window.scrollTo({{
    top: Math.max(0, rowTop - headerHeight - centeredOffset),
    behavior: 'smooth',
  }});
}};

const updateSelection = ({{ center = false }} = {{}}) => {{
  document.querySelector('.alignment-row.is-current')?.classList.remove('is-current');
  document.querySelector('[data-select-section][aria-current="true"]')?.removeAttribute('aria-current');
  currentRow()?.classList.add('is-current');
  currentRow()?.querySelector('[data-select-section]')?.setAttribute('aria-current', 'true');
  previousSegment.disabled = currentIndex === 0;
  nextSegment.disabled = currentIndex === audioUnits.length - 1;
  updateStatus();
  if (center) centerCurrent();
}};

const cachedAudioResponse = async () => {{
  if (!('caches' in window)) return null;
  return (await caches.open(AUDIO_CACHE)).match(AUDIO_URL);
}};

const ensureAudioSource = async () => {{
  if (!player.src) {{
    const cached = await cachedAudioResponse();
    if (cached) {{
      audioObjectUrl = URL.createObjectURL(await cached.blob());
      player.src = audioObjectUrl;
    }} else {{
      player.src = AUDIO_URL;
    }}
  }}
  if (player.readyState < HTMLMediaElement.HAVE_METADATA) {{
    await new Promise((resolve, reject) => {{
      player.addEventListener('loadedmetadata', resolve, {{ once: true }});
      player.addEventListener('error', () => reject(new Error('The audiobook could not be loaded.')), {{ once: true }});
      player.load();
    }});
  }}
  player.playbackRate = playbackRate;
}};

const seekToCurrentStart = () => {{
  player.currentTime = Number(currentUnit().audio.start);
}};

const beginCurrent = async ({{ resetCounter = true, resume = false }} = {{}}) => {{
  if (loadingAudio || !currentUnit()) return;
  loadingAudio = true;
  playSegmentButton.disabled = true;
  playbackVersion += 1;
  try {{
    await ensureAudioSource();
    if (resetCounter) completedRepeats = 0;
    handlingSegmentEnd = false;
    const resumeTime = pendingResumeTime ?? player.currentTime;
    if (
      resume
      && Number.isFinite(resumeTime)
      && resumeTime >= Number(currentUnit().audio.start)
      && resumeTime < Number(currentUnit().audio.end) - 0.025
    ) player.currentTime = resumeTime;
    else seekToCurrentStart();
    pendingResumeTime = null;
    saveProgress(player.currentTime);
    await player.play();
    clearInterval(segmentMonitor);
    segmentMonitor = setInterval(checkSegmentEnd, 40);
    setPlayingUI(true);
  }} catch (error) {{
    setPlayingUI(false);
    announceAudio(error.message || 'Audio playback failed.');
  }} finally {{
    loadingAudio = false;
    playSegmentButton.disabled = false;
  }}
}};

const pauseCurrent = () => {{
  playbackVersion += 1;
  player.pause();
  clearInterval(segmentMonitor);
  segmentMonitor = null;
  handlingSegmentEnd = false;
  saveProgress();
  setPlayingUI(false);
}};

const finishCurrent = () => {{
  playbackVersion += 1;
  player.pause();
  if (currentUnit()) player.currentTime = Number(currentUnit().audio.end);
  clearInterval(segmentMonitor);
  segmentMonitor = null;
  handlingSegmentEnd = false;
  saveProgress();
  setPlayingUI(false);
}};

const advanceAfterCurrent = () => {{
  if (currentIndex >= audioUnits.length - 1) {{
    finishCurrent();
    return;
  }}
  playbackVersion += 1;
  player.pause();
  clearInterval(segmentMonitor);
  segmentMonitor = null;
  handlingSegmentEnd = false;
  currentIndex += 1;
  completedRepeats = 0;
  pendingResumeTime = null;
  updateSelection({{ center: true }});
  saveProgress(Number(currentUnit().audio.start));
  beginCurrent({{ resetCounter: false }});
}};

const checkSegmentEnd = () => {{
  const unit = currentUnit();
  if (
    !unit ||
    handlingSegmentEnd ||
    player.currentTime < Number(unit.audio.end) - 0.025
  ) return;
  handlingSegmentEnd = true;
  if (completedRepeats + 1 < totalPlays()) {{
    completedRepeats += 1;
    const version = playbackVersion;
    player.addEventListener('seeked', () => {{
      if (version !== playbackVersion) return;
      handlingSegmentEnd = false;
      if (segmentMonitor !== null) player.play().catch(() => finishCurrent());
    }}, {{ once: true }});
    seekToCurrentStart();
    updateStatus();
  }} else {{
    advanceAfterCurrent();
  }}
}};

const moveCurrent = direction => {{
  if (!audioUnits.length) return;
  const wasPlaying = isPlaying();
  playbackVersion += 1;
  player.pause();
  clearInterval(segmentMonitor);
  segmentMonitor = null;
  handlingSegmentEnd = false;
  currentIndex = Math.max(0, Math.min(audioUnits.length - 1, currentIndex + direction));
  completedRepeats = 0;
  pendingResumeTime = null;
  updateSelection({{ center: true }});
  saveProgress(Number(currentUnit().audio.start));
  if (wasPlaying) beginCurrent();
  else setPlayingUI(false);
}};

const selectSection = id => {{
  if (loadingAudio) return;
  const index = audioUnits.findIndex(unit => unit.id === id);
  if (index < 0) return;
  playbackVersion += 1;
  player.pause();
  clearInterval(segmentMonitor);
  segmentMonitor = null;
  handlingSegmentEnd = false;
  currentIndex = index;
  completedRepeats = 0;
  pendingResumeTime = null;
  updateSelection({{ center: true }});
  saveProgress(Number(currentUnit().audio.start));
  setPlayingUI(false);
  playerStatus.textContent = `Section ${{currentIndex + 1}} selected · press Play`;
  announceAudio(`Section ${{currentIndex + 1}} selected for playback. Press Play to start.`);
}};

playSegmentButton.addEventListener('click', () => {{
  if (isPlaying()) pauseCurrent();
  else {{
    const resume = canResumeCurrent();
    beginCurrent({{ resetCounter: !resume, resume }});
  }}
}});
previousSegment.addEventListener('click', () => moveCurrent(-1));
nextSegment.addEventListener('click', () => moveCurrent(1));
document.querySelectorAll('[data-select-section]').forEach(button => {{
  button.addEventListener('click', () => selectSection(button.dataset.selectSection));
}});
repeatSegment.addEventListener('click', () => {{
  repeatIndex = (repeatIndex + 1) % REPEAT_OPTIONS.length;
  completedRepeats = 0;
  updateRepeatControl({{ persist: true }});
  updateStatus();
}});
centerSegment.addEventListener('click', centerCurrent);
player.addEventListener('timeupdate', () => {{
  const second = Math.floor(player.currentTime);
  if (second !== lastSavedProgressSecond) {{
    lastSavedProgressSecond = second;
    saveProgress();
  }}
  checkSegmentEnd();
}});
player.addEventListener('ended', checkSegmentEnd);
document.addEventListener('visibilitychange', () => {{
  if (document.visibilityState === 'hidden') saveProgress();
}});
window.addEventListener('pagehide', () => saveProgress());

const loadAudioMap = async () => {{
  try {{
    const response = await fetch(AUDIO_MAP_URL);
    if (!response.ok) throw new Error(`Timestamp request failed (${{response.status}}).`);
    const payload = await response.json();
    const rowsById = new Map(rows.map(row => [row.id, row]));
    audioUnits = payload.units
      .map(unit => ({{ ...unit, row: rowsById.get(unit.id) }}))
      .filter(unit => unit.row);
    audioUnits.forEach(unit => {{
      unit.row.dataset.audioStart = unit.audio.start;
      unit.row.dataset.audioEnd = unit.audio.end;
      unit.row.querySelector('[data-select-section]').disabled = false;
    }});
    if (!audioUnits.length) throw new Error('No timestamped sections were found.');
    const savedProgress = readSavedProgress();
    const savedIndex = savedProgress
      ? audioUnits.findIndex(unit => unit.id === savedProgress.unitId)
      : -1;
    if (savedIndex >= 0) {{
      currentIndex = savedIndex;
      const savedTime = Number(savedProgress.time);
      if (
        Number.isFinite(savedTime)
        && savedTime >= Number(currentUnit().audio.start)
        && savedTime < Number(currentUnit().audio.end) - 0.025
      ) pendingResumeTime = savedTime;
    }}
    [playSegmentButton, repeatSegment, speedToggle, centerSegment].forEach(button => {{
      button.disabled = false;
    }});
    updateSelection({{ center: savedIndex >= 0 }});
  }} catch (error) {{
    playerStatus.textContent = 'Timestamps unavailable';
    announceAudio(error.message || 'Timestamps are unavailable.');
  }}
}};

const setOfflineState = async () => {{
  if (!window.isSecureContext || !('caches' in window) || !('serviceWorker' in navigator)) {{
    offlineButton.textContent = 'Offline audio needs HTTPS';
    offlineButton.disabled = true;
    announceAudio('Audio can stream, but offline saving requires HTTPS or localhost.');
    return;
  }}
  const cached = await cachedAudioResponse();
  if (cached) {{
    offlineButton.textContent = 'Audiobook saved ✓';
    offlineButton.disabled = true;
    offlinePrompt.hidden = true;
    announceAudio('The audiobook is available offline.');
    return;
  }}
  offlineButton.textContent = 'Save audio · 149 MB';
  offlineButton.disabled = false;
  if (!localStorage.getItem('viscount-offline-prompt-dismissed')) {{
    if (speedPanel.hidden) offlinePrompt.hidden = false;
    else restoreOfflinePromptAfterSpeed = true;
  }}
}};

const saveAudioOffline = async () => {{
  offlinePrompt.hidden = true;
  offlineButton.disabled = true;
  offlineButton.textContent = 'Saving audiobook…';
  announceAudio('Saving the audiobook. Keep this page open until it finishes.');
  try {{
    if (navigator.storage?.persist) await navigator.storage.persist();
    const response = await fetch(AUDIO_URL, {{ cache: 'no-store' }});
    if (!response.ok || response.status === 206) throw new Error('The server did not return the complete audiobook.');
    await (await caches.open(AUDIO_CACHE)).put(AUDIO_URL, response);
    if (audioObjectUrl) URL.revokeObjectURL(audioObjectUrl);
    audioObjectUrl = null;
    player.removeAttribute('src');
    player.load();
    await setOfflineState();
  }} catch (error) {{
    offlineButton.textContent = 'Retry saving audio';
    offlineButton.disabled = false;
    announceAudio(error.message || 'The audiobook could not be saved.');
  }}
}};

offlineButton.addEventListener('click', saveAudioOffline);
document.querySelector('#save-audio').addEventListener('click', saveAudioOffline);
document.querySelector('#dismiss-offline').addEventListener('click', () => {{
  localStorage.setItem('viscount-offline-prompt-dismissed', 'true');
  offlinePrompt.hidden = true;
}});

const startOfflineSupport = async () => {{
  if ('serviceWorker' in navigator && window.isSecureContext) {{
    try {{
      await navigator.serviceWorker.register('./service-worker.js');
      await navigator.serviceWorker.ready;
    }} catch (error) {{
      announceAudio(`Offline setup failed: ${{error.message}}`);
    }}
  }}
  await setOfflineState();
}};

loadAudioMap();
startOfflineSupport();
</script>
</body>
</html>
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")


EPUB_CSS = """
body {
  margin: 0;
  color: #242321;
  background: #ffffff;
  font-family: serif;
  line-height: 1.45;
}
h1 {
  margin: 0 0 1.2em;
  padding: 0.5em 0.35em;
  border-bottom: 0.12em solid #d8d4cc;
  font-family: sans-serif;
  font-size: 1.15em;
  font-weight: bold;
}
h1 .italian-title { color: #176c54; }
h1 .english-title { color: #9a3e38; }
table.parallel-text {
  width: 100%;
  border: 0;
  border-collapse: collapse;
  table-layout: fixed;
}
table.parallel-text th {
  padding: 0.55em 0.45em;
  border-bottom: 0.12em solid #bdb8ae;
  font-family: sans-serif;
  font-size: 0.72em;
  text-align: left;
  text-transform: uppercase;
}
table.parallel-text th.italian { color: #176c54; }
table.parallel-text th.english { color: #9a3e38; }
table.parallel-text td {
  width: 50%;
  padding: 0.7em 0.5em 0.8em;
  border-bottom: 0.06em solid #ddd9d1;
  vertical-align: top;
  -webkit-hyphens: auto;
  hyphens: auto;
  overflow-wrap: break-word;
}
table.parallel-text td.english,
table.parallel-text th.english {
  border-left: 0.06em solid #d2cec5;
}
table.parallel-text tr {
  break-inside: avoid;
  page-break-inside: avoid;
}
table.parallel-text p { margin: 0; }
table.parallel-text p + p { margin-top: 0.6em; }
.supplement {
  display: block;
  margin: 0 0 0.45em;
  color: #7c5400;
  font-family: sans-serif;
  font-size: 0.62em;
  font-weight: bold;
  text-transform: uppercase;
}
.cover-page {
  margin: 0;
  padding: 0;
  text-align: center;
}
.cover-page img {
  width: auto;
  max-width: 100%;
  height: auto;
  max-height: 95vh;
}
"""


def _epub_unit_row(unit: AlignmentUnit) -> str:
    supplement = (
        '<span class="supplement">Supplement</span>'
        if unit.confidence == "supplemental"
        else ""
    )
    return (
        f'<tr id="{unit.id}">'
        f'<td class="italian" lang="it">{_sentence_lines(unit.italian)}</td>'
        f'<td class="english" lang="en">{supplement}{_sentence_lines(unit.english)}</td>'
        "</tr>"
    )


def render_epub(
    units: tuple[AlignmentUnit, ...],
    italian_source: SourceSpec,
    english_source: SourceSpec,
    destination: Path,
) -> None:
    book = epub.EpubBook()
    book.set_identifier("viscount-bilingual-alignment-v1")
    book.set_title("Il visconte dimezzato · The Cloven Viscount")
    book.set_language("it")
    book.add_metadata("DC", "language", "en")
    book.add_author("Italo Calvino")
    book.add_metadata(
        "DC",
        "description",
        "Italian-English parallel text aligned for language learning.",
    )
    book.add_metadata("DC", "source", italian_source.edition)
    book.add_metadata("DC", "source", english_source.edition)

    cover_asset = _cover_asset(italian_source)
    cover_page = None
    if cover_asset is not None:
        mime, cover_content = cover_asset
        extension = "png" if mime == "image/png" else "jpg"
        cover_name = f"cover.{extension}"
        book.set_cover(cover_name, cover_content, create_page=False)
        cover_page = epub.EpubHtml(
            title="Cover",
            file_name="cover.xhtml",
            lang="it",
        )
        cover_page.content = (
            '<div class="cover-page">'
            f'<img src="{cover_name}" alt="Il visconte dimezzato cover" />'
            "</div>"
        )

    stylesheet = epub.EpubItem(
        uid="parallel-style",
        file_name="styles/parallel.css",
        media_type="text/css",
        content=EPUB_CSS,
    )
    book.add_item(stylesheet)

    chapters: list[epub.EpubHtml] = []
    for chapter_number in range(1, 11):
        rows = "\n".join(
            _epub_unit_row(unit) for unit in units if unit.chapter == chapter_number
        )
        chapter = epub.EpubHtml(
            title=f"Capitolo {chapter_number} · Chapter {chapter_number}",
            file_name=f"chapter-{chapter_number}.xhtml",
            lang="it",
        )
        chapter.content = f"""
<h1><span class="italian-title" lang="it">Capitolo {chapter_number}</span>
  · <span class="english-title" lang="en">Chapter {chapter_number}</span></h1>
<table class="parallel-text">
  <colgroup><col style="width:50%" /><col style="width:50%" /></colgroup>
  <thead><tr><th class="italian" lang="it">Italiano</th><th class="english" lang="en">English</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
"""
        chapter.add_item(stylesheet)
        chapters.append(chapter)
        book.add_item(chapter)

    if cover_page is not None:
        cover_page.add_item(stylesheet)
        book.add_item(cover_page)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ([cover_page] if cover_page is not None else []) + chapters

    destination.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(destination), book, {})
