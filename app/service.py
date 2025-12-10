# app/service.py
from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import api as workspace_api


app = FastAPI(title="AI Workbench – Workspace Agent")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/guides", StaticFiles(directory="data/study_guides"), name="guides")
templates = Jinja2Templates(directory="templates")


class WorkspaceQueryBody(BaseModel):
    question: str
    top_k: int = 8
    mode: str = "copilot"   # "rag_only" | "copilot" | "manager_auto" | "study_guide"


def _default_state() -> Dict[str, Any]:
    return {
        "mode": "copilot",
        "question": "",
        "top_k": 8,
        "answer": "",
        "rag": None,
        "copilot": None,
        "agent_trace": [],
        "markdown_url": None,
        "pdf_url": None,
    }


def _render_index(request: Request, state: Dict[str, Any]) -> HTMLResponse:
    ctx = {"request": request, "state": state}
    return templates.TemplateResponse("index.html", ctx)


# ---------- HTML UI ----------


@app.get("/", response_class=HTMLResponse)
async def workspace_home(request: Request):
    return _render_index(request, _default_state())


@app.post("/workspace/query", response_class=HTMLResponse)
async def workspace_query(
    request: Request,
    question: str = Form(default=""),
    top_k: int = Form(default=8),
    mode: str = Form(default="copilot"),
):
    result = workspace_api.ask_workspace(
        question=question,
        top_k=top_k,
        mode=mode,
    )
    return _render_index(request, result)


# ---------- JSON API ----------


@app.post("/api/query", response_class=JSONResponse)
async def api_query(body: WorkspaceQueryBody):
    result = workspace_api.ask_workspace(
        question=body.question,
        top_k=body.top_k,
        mode=body.mode,
    )
    return JSONResponse(content=result)


@app.get("/healthz", response_class=JSONResponse)
async def healthz():
    try:
        return {"status": "ok", "service": "workspace-agent"}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "service": "workspace-agent"},
        )
