import csv
import io
import secrets
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .. import charting, crud, queries
from ..config import get_settings
from ..db import get_db

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def require_login(request: Request) -> None:
    if not request.session.get("logged_in"):
        raise HTTPException(status_code=303, headers={"Location": "/_gateway/login"})


@router.get("/_gateway/login")
def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/_gateway/login")
def login_submit(request: Request, password: str = Form(...)):
    settings = get_settings()
    if secrets.compare_digest(password, settings.dashboard_password):
        request.session["logged_in"] = True
        return RedirectResponse(url="/_gateway/dashboard", status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "密碼錯誤"}, status_code=401
    )


@router.get("/_gateway/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/_gateway/login", status_code=303)


@router.get("/_gateway/dashboard")
def dashboard_home(
    request: Request, _: None = Depends(require_login), conn: sqlite3.Connection = Depends(get_db)
):
    projects = queries.dashboard_overview(conn)
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "projects": projects}
    )


@router.post("/_gateway/dashboard/projects")
def create_project(
    request: Request,
    name: str = Form(...),
    _: None = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name must not be empty")
    project = crud.create_project(conn, name)
    raw_key = crud.create_api_key(conn, project.id)
    return templates.TemplateResponse(
        "key_created.html",
        {
            "request": request,
            "heading": f"「{project.name}」建立完成",
            "raw_key": raw_key,
            "continue_url": f"/_gateway/dashboard/{project.id}",
        },
    )


@router.get("/_gateway/dashboard/{project_id}")
def project_detail(
    request: Request,
    project_id: int,
    tab: str = "overview",
    _: None = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    project = crud.get_project(conn, project_id)
    if project is None:
        raise HTTPException(status_code=404)

    context = {"request": request, "project": project, "tab": tab}
    if tab == "overview":
        context["summary"] = queries.project_summary(conn, project_id)
        context["chart_svg"] = charting.render_daily_bar_chart(
            queries.daily_totals(conn, project_id)
        )
    elif tab in ("label", "model"):
        context["breakdown"] = queries.breakdown_by(conn, project_id, tab)
    elif tab == "requests":
        context["requests"] = queries.recent_requests(conn, project_id)
        context["api_keys"] = crud.list_api_keys(conn, project_id)

    return templates.TemplateResponse("project_detail.html", context)


@router.post("/_gateway/dashboard/{project_id}/toggle-status")
def toggle_project_status(
    project_id: int,
    _: None = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    project = crud.get_project(conn, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    new_status = "disabled" if project.status == "active" else "active"
    crud.set_project_status(conn, project_id, new_status)
    return RedirectResponse(url=f"/_gateway/dashboard/{project_id}", status_code=303)


@router.get("/_gateway/dashboard/{project_id}/requests.json")
def requests_json(
    project_id: int,
    after_id: int = 0,
    _: None = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    rows = queries.recent_requests(conn, project_id, after_id=after_id)
    return JSONResponse({"requests": rows})


@router.post("/_gateway/dashboard/{project_id}/keys")
def create_key(
    request: Request,
    project_id: int,
    _: None = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    if crud.get_project(conn, project_id) is None:
        raise HTTPException(status_code=404)
    raw_key = crud.create_api_key(conn, project_id)
    return templates.TemplateResponse(
        "key_created.html",
        {
            "request": request,
            "heading": "新 Key 已產生",
            "raw_key": raw_key,
            "continue_url": f"/_gateway/dashboard/{project_id}?tab=requests",
        },
    )


@router.post("/_gateway/dashboard/{project_id}/keys/{key_id}/revoke")
def revoke_key(
    project_id: int,
    key_id: int,
    _: None = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    key_belongs_to_project = any(k["id"] == key_id for k in crud.list_api_keys(conn, project_id))
    if not key_belongs_to_project:
        raise HTTPException(status_code=404)
    crud.revoke_api_key(conn, key_id)
    return RedirectResponse(url=f"/_gateway/dashboard/{project_id}?tab=requests", status_code=303)


_EXPORT_TABS = ("requests", "label", "model")


@router.get("/_gateway/dashboard/{project_id}/export.csv")
def export_csv(
    project_id: int,
    tab: str = "requests",
    _: None = Depends(require_login),
    conn: sqlite3.Connection = Depends(get_db),
):
    if crud.get_project(conn, project_id) is None:
        raise HTTPException(status_code=404)
    if tab not in _EXPORT_TABS:
        raise HTTPException(status_code=400, detail=f"tab must be one of {_EXPORT_TABS}")

    buffer = io.StringIO()
    if tab in ("label", "model"):
        rows = queries.breakdown_by(conn, project_id, tab)
        writer = csv.DictWriter(buffer, fieldnames=["key", "request_count", "total_tokens"])
        writer.writeheader()
        writer.writerows(rows)
    else:
        rows = queries.recent_requests(conn, project_id, limit=10_000)
        writer = csv.DictWriter(
            buffer,
            fieldnames=[
                "id", "created_at", "label", "model", "endpoint_path",
                "prompt_tokens", "completion_tokens", "total_tokens", "status_code",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=project-{project_id}-{tab}.csv"},
    )
