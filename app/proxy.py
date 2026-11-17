import json
import sqlite3
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from starlette.requests import Request as StarletteRequest
from starlette.responses import StreamingResponse

from . import crud
from .config import Settings, get_settings
from .crud import Project
from .db import get_connection, get_db


def resolve_project(
    authorization: str = Header(default=None), conn: sqlite3.Connection = Depends(get_db)
) -> Project:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key")

    raw_key = authorization[len("Bearer "):]
    project = crud.get_project_by_key(conn, raw_key)
    if project is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if project.status != "active":
        raise HTTPException(status_code=403, detail="Project is disabled")
    return project


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


router = APIRouter()

_HOP_BY_HOP_REQUEST_HEADERS = {"host", "content-length", "authorization", "x-task-label"}
_HOP_BY_HOP_RESPONSE_HEADERS = {"content-length", "transfer-encoding", "content-encoding"}


def _build_forward_headers(request: StarletteRequest, settings: Settings) -> dict:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP_REQUEST_HEADERS}
    headers["authorization"] = f"Bearer {settings.backend_api_key}"
    headers["accept-encoding"] = "identity"
    return headers


def _filter_response_headers(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(
    path: str,
    request: Request,
    project: Project = Depends(resolve_project),
    conn: sqlite3.Connection = Depends(get_db),
    client: httpx.AsyncClient = Depends(get_http_client),
):
    settings = get_settings()
    body = await request.body()
    label = request.headers.get("x-task-label")
    forward_headers = _build_forward_headers(request, settings)
    target_url = f"{settings.backend_base_url.rstrip('/')}/{path}"

    json_body = None
    content_type = request.headers.get("content-type", "")
    if body and "application/json" in content_type:
        try:
            json_body = json.loads(body)
        except ValueError:
            json_body = None
    model = (json_body or {}).get("model")

    is_streaming = bool(json_body and json_body.get("stream"))

    injected_include_usage = False
    if is_streaming and json_body is not None:
        stream_options = json_body.get("stream_options") or {}
        if not stream_options.get("include_usage"):
            json_body["stream_options"] = {**stream_options, "include_usage": True}
            injected_include_usage = True
            body = json.dumps(json_body).encode("utf-8")

    if is_streaming:
        return await _proxy_streaming(
            client, request.method, target_url, request.query_params, forward_headers, body,
            conn, project, label, model, path, injected_include_usage, settings.request_timeout_seconds,
        )
    return await _proxy_non_streaming(
        client, request.method, target_url, request.query_params, forward_headers, body,
        conn, project, label, model, path, settings.request_timeout_seconds,
    )


async def _proxy_non_streaming(
    client, method, target_url, query_params, headers, body, conn, project, label, model, path,
    timeout_seconds,
):
    start = time.monotonic()
    try:
        resp = await client.request(
            method, target_url, params=query_params, headers=headers, content=body,
            timeout=timeout_seconds,
        )
    except httpx.HTTPError:
        latency_ms = int((time.monotonic() - start) * 1000)
        crud.log_request(
            conn, project_id=project.id, label=label, model=model, endpoint_path=f"/{path}",
            method=method, is_streaming=False, prompt_tokens=None, completion_tokens=None,
            total_tokens=None, status_code=502, latency_ms=latency_ms,
        )
        return Response(content=b"Bad Gateway: failed to forward request.\n", status_code=502)

    latency_ms = int((time.monotonic() - start) * 1000)

    usage = {}
    try:
        parsed_usage = resp.json().get("usage")
        if isinstance(parsed_usage, dict):
            usage = parsed_usage
    except ValueError:
        pass

    crud.log_request(
        conn, project_id=project.id, label=label, model=model, endpoint_path=f"/{path}",
        method=method, is_streaming=False, prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"), total_tokens=usage.get("total_tokens"),
        status_code=resp.status_code, latency_ms=latency_ms,
    )

    response_headers = _filter_response_headers(resp.headers)
    return Response(content=resp.content, status_code=resp.status_code, headers=response_headers)


def _parse_json_object(payload: str) -> dict | None:
    try:
        parsed = json.loads(payload)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _sse_data_payload(line: str) -> str | None:
    """Extract the payload of an SSE `data:` line, if this line is one.

    Per the SSE spec, at most one leading space after the colon is stripped
    (not arbitrary whitespace) — and that space is optional to begin with.
    Some OpenAI-compatible backends omit it (`data:{...}` instead of the more
    common `data: {...}`), so don't require it.
    """
    if not line.startswith("data:"):
        return None
    payload = line[len("data:"):]
    if payload.startswith(" "):
        payload = payload[1:]
    return payload


async def _proxy_streaming(
    client, method, target_url, query_params, headers, body,
    conn, project, label, model, path, injected_include_usage, timeout_seconds,
):
    start = time.monotonic()
    stream_ctx = client.stream(
        method, target_url, params=query_params, headers=headers, content=body,
        timeout=timeout_seconds,
    )
    try:
        resp = await stream_ctx.__aenter__()
    except httpx.HTTPError:
        latency_ms = int((time.monotonic() - start) * 1000)
        crud.log_request(
            conn, project_id=project.id, label=label, model=model, endpoint_path=f"/{path}",
            method=method, is_streaming=True, prompt_tokens=None, completion_tokens=None,
            total_tokens=None, status_code=502, latency_ms=latency_ms,
        )
        return Response(content=b"Bad Gateway: failed to forward request.\n", status_code=502)

    status_code = resp.status_code
    response_headers = _filter_response_headers(resp.headers)

    async def event_stream():
        usage = {}
        try:
            async for line in resp.aiter_lines():
                payload = _sse_data_payload(line)
                if payload is not None and payload.strip() != "[DONE]":
                    chunk = _parse_json_object(payload)
                    if chunk is not None:
                        chunk_usage = chunk.get("usage")
                        if isinstance(chunk_usage, dict):
                            usage = chunk_usage
                            if injected_include_usage:
                                if not chunk.get("choices"):
                                    # Purely synthetic usage-only chunk (the
                                    # OpenAI-standard shape): drop it entirely,
                                    # the client never asked for it.
                                    continue
                                # Some OpenAI-compatible backends (e.g.
                                # vLLM-style servers) attach usage to the same
                                # chunk as the final finish_reason/content
                                # instead of a separate usage-only chunk. That
                                # chunk has real content the client still
                                # needs, so forward it — just without the
                                # usage field the client never asked for.
                                del chunk["usage"]
                                line = f"data: {json.dumps(chunk)}"
                yield (line + "\n").encode("utf-8")
        finally:
            await stream_ctx.__aexit__(None, None, None)
            latency_ms = int((time.monotonic() - start) * 1000)
            # `conn` (injected via Depends(get_db)) may already be closed by now:
            # FastAPI closes yield-dependencies right after the route handler
            # returns the StreamingResponse object, not after the streamed body
            # actually finishes sending. Use a fresh, independently-managed
            # connection for this deferred write instead of relying on `conn`.
            log_conn = get_connection(get_settings().database_path)
            try:
                crud.log_request(
                    log_conn, project_id=project.id, label=label, model=model,
                    endpoint_path=f"/{path}", method=method, is_streaming=True,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens"), status_code=status_code,
                    latency_ms=latency_ms,
                )
            finally:
                log_conn.close()

    return StreamingResponse(
        event_stream(), status_code=status_code, headers=response_headers,
        media_type="text/event-stream",
    )
