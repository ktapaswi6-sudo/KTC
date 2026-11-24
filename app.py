from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine import BASE, EXPORTS, health, ollama_models, process_job
from prompts import PRESETS

app = FastAPI(title="KTC Studio")
EXPORTS.mkdir(exist_ok=True)
app.mount("/exports", StaticFiles(directory=str(EXPORTS)), name="exports")
pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ktc")
lock = threading.Lock()
jobs: dict[str, dict[str, Any]] = {}


class Request(BaseModel):
    source: str = Field(min_length=1, max_length=2048)
    count: int = Field(default=5, ge=1, le=10)
    length: str = "30-60"
    preset: str = "Viral Hook & Payoff"
    custom: str = ""
    ai: str = "ollama"
    ollama_model: str = "llama3.1"
    gemini_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    whisper: str = "small"
    color: str = "#C6FF00"
    font: str = "Anton"
    remove_pauses: bool = True


def worker(job_id: str, data: dict[str, Any]) -> None:
    try:
        process_job(job_id, data, jobs)
    except Exception as exc:
        jobs[job_id].update(status="error", error=str(exc), message=str(exc))
    finally:
        lock.release()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return health()


@app.get("/api/presets")
def api_presets() -> dict[str, Any]:
    return {"presets": PRESETS}


@app.get("/api/ollama/models")
def api_models() -> dict[str, Any]:
    return {"models": ollama_models()}


@app.post("/api/jobs", status_code=202)
def create_job(body: Request) -> dict[str, str]:
    data = body.model_dump()
    if data["length"] not in {"15-30", "30-60", "60-90"}:
        raise HTTPException(422, "Choose a supported clip duration.")
    if data["ai"] not in {"ollama", "gemini", "heuristic"}:
        raise HTTPException(422, "Choose Ollama, Gemini, or local heuristic.")
    if data["whisper"] not in {"base", "small", "medium"}:
        raise HTTPException(422, "Choose base, small, or medium Whisper.")
    if data["preset"] not in PRESETS:
        raise HTTPException(422, "Unknown creative preset.")
    if data["ai"] == "gemini" and not data["gemini_key"].strip():
        raise HTTPException(422, "Gemini API key is required for Gemini.")
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "A KTC job is already running.")
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"id": job_id, "status": "queued", "step": 0, "progress": 0,
                    "message": "Queued", "warnings": [], "clips": [], "error": None}
    pool.submit(worker, job_id, data)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/download/{job_id}/{filename}")
def download(job_id: str, filename: str) -> FileResponse:
    if not job_id.isalnum() or not filename or Path(filename).name != filename:
        raise HTTPException(400, "Invalid download path.")
    folder = (EXPORTS / job_id).resolve()
    path = (folder / filename).resolve()
    if folder not in path.parents or not path.is_file():
        raise HTTPException(404, "File not found.")
    return FileResponse(path, filename=path.name)
