from __future__ import annotations

from typing import Iterable

import httpx
from fastapi import FastAPI, Request, Response

SUPERPLANE_BASE = "http://127.0.0.1:3000"
FASTAPI_BASE = "http://127.0.0.1:8011"
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}

app = FastAPI(title="StarStarter Gateway")


def _forward_headers(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    return {k: v for k, v in headers if k.lower() not in HOP_BY_HOP_HEADERS}


async def _proxy(request: Request, upstream_base: str) -> Response:
    upstream_url = f"{upstream_base}{request.url.path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    body = await request.body()

    async with httpx.AsyncClient(follow_redirects=False, timeout=30.0) as client:
        upstream_response = await client.request(
            method=request.method,
            url=upstream_url,
            headers=_forward_headers(request.headers.items()),
            content=body,
        )

    response_headers = _forward_headers(upstream_response.headers.items())
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )


@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_superplane_api(path: str, request: Request) -> Response:
    del path
    return await _proxy(request, SUPERPLANE_BASE)


@app.api_route("/webhooks/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_fastapi_webhooks(path: str, request: Request) -> Response:
    del path
    return await _proxy(request, FASTAPI_BASE)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_superplane_ui(path: str, request: Request) -> Response:
    del path
    return await _proxy(request, SUPERPLANE_BASE)
