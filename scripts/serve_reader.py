"""Serve the generated reader locally with HTTP byte-range support."""

from __future__ import annotations

import argparse
import os
import re
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit

from viscount_aligner.paths import SITE_DIR
from viscount_aligner.site import sync_web_assets

class ReaderHandler(SimpleHTTPRequestHandler):
    """Serve the reader and support the byte ranges browsers use for audio."""

    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".webm": "audio/webm",
        ".webmanifest": "application/manifest+json",
        ".svg": "image/svg+xml",
    }

    def _rewrite_root(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == "/":
            self.path = urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    "/viscount-bilingual.html",
                    parts.query,
                    parts.fragment,
                )
            )

    def do_GET(self) -> None:
        self._rewrite_root()
        super().do_GET()

    def do_HEAD(self) -> None:
        self._rewrite_root()
        super().do_HEAD()

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            source = open(path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        size = os.fstat(source.fileno()).st_size
        self._range = None
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match or not any(match.groups()):
                source.close()
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return None
            if match.group(1):
                start = int(match.group(1))
                end = (
                    min(int(match.group(2)), size - 1)
                    if match.group(2)
                    else size - 1
                )
            else:
                length = min(int(match.group(2)), size)
                start, end = size - length, size - 1
            if start >= size or start > end:
                source.close()
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            self._range = (start, end)

        status = HTTPStatus.PARTIAL_CONTENT if self._range else HTTPStatus.OK
        start, end = self._range or (0, size - 1)
        self.send_response(status)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if self._range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        return source

    def copyfile(self, source, outputfile) -> None:
        if not self._range:
            return super().copyfile(source, outputfile)
        start, end = self._range
        source.seek(start)
        remaining = end - start + 1
        while remaining:
            block = source.read(min(64 * 1024, remaining))
            if not block:
                break
            try:
                outputfile.write(block)
            except (BrokenPipeError, ConnectionResetError):
                break
            remaining -= len(block)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the bilingual reader and audiobook.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    sync_web_assets()
    handler = partial(ReaderHandler, directory=str(SITE_DIR))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f"Reader: http://{args.host}:{server.server_port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
