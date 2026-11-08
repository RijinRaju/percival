"""Serves the built web UI. Any path that isn't the API gets index.html so
client-side routes survive a page reload."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# only for the ui pages, the swagger page at /api/docs pulls from a cdn
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'"
)
UI_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}
RESERVED = ("api/", "api", "health")


def mount(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    assets = static_dir / "assets"
    if assets.is_dir():
        # file names carry a content hash, so they can be cached for good
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str, request: Request) -> FileResponse:
        if path.startswith(RESERVED) or not index.is_file():
            raise HTTPException(404)
        return FileResponse(index, headers={**UI_HEADERS, "Cache-Control": "no-cache"})
