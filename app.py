from __future__ import annotations

import json
import secrets
import threading
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine import BASE, CACHE, EXPORTS, health, ollama_models, process_job
from prompts import PRESETS

app = FastAPI(title="KTC Studio")
EXPORTS.mkdir(exist_ok=True)
app.mount("/exports", StaticFiles(directory=str(EXPORTS)), name="exports")
pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ktc")
lock = threading.Lock()
jobs: dict[str, dict[str, Any]] = {}
oauth_states: set[str] = set()
state_lock = threading.Lock()
TOKEN_FILE = CACHE / "youtube_token.json"
CLIENT_FILE = BASE / "client_secrets.json"
SCHEDULE_FILE = CACHE / "youtube_schedule.json"
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]
REDIRECT_URI = "http://127.0.0.1:8000/oauth/callback"
IST = ZoneInfo("Asia/Kolkata")


class JobRequest(BaseModel):
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


class TrendRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=100)
    api_key: str = Field(min_length=10, max_length=256)


class ScheduleRequest(BaseModel):
    job_id: str
    filename: str
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    hashtags: list[str] = Field(default_factory=list, max_length=20)
    scheduled_at: datetime
    approved: bool = False


def _worker(job_id: str, data: dict[str, Any]) -> None:
    try:
        process_job(job_id, data, jobs)
    except Exception as exc:
        jobs[job_id].update(status="error", error=str(exc), message=str(exc))
    finally:
        lock.release()


def _google_auth() -> Any:
    if not TOKEN_FILE.is_file():
        raise HTTPException(401, "Connect your YouTube channel first.")
    try:
        from google.oauth2.credentials import Credentials
        credentials = Credentials.from_authorized_user_file(str(TOKEN_FILE), OAUTH_SCOPES)
        if credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request as GoogleRequest
            credentials.refresh(GoogleRequest())
            TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
        if not credentials.valid:
            raise HTTPException(401, "YouTube access expired. Connect your channel again.")
        return credentials
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, f"Could not read YouTube authorization: {exc}") from exc


def _youtube() -> Any:
    try:
        from googleapiclient.discovery import build
        return build("youtube", "v3", credentials=_google_auth(), cache_discovery=False)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, f"YouTube API unavailable: {exc}") from exc


def _schedule_history() -> list[dict[str, Any]]:
    try:
        value = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    result = health()
    result["youtube_oauth_configured"] = CLIENT_FILE.is_file()
    result["youtube_connected"] = TOKEN_FILE.is_file()
    return result


@app.get("/api/presets")
def api_presets() -> dict[str, Any]:
    return {"presets": PRESETS}


@app.get("/api/ollama/models")
def api_models() -> dict[str, Any]:
    return {"models": ollama_models()}


@app.post("/api/jobs", status_code=202)
def create_job(body: JobRequest) -> dict[str, str]:
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
    pool.submit(_worker, job_id, data)
    return {"id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.get("/api/jobs/{job_id}/bundle")
def download_bundle(job_id: str) -> FileResponse:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    folder = (EXPORTS / job_id).resolve()
    if not folder.is_dir() or EXPORTS.resolve() not in folder.parents:
        raise HTTPException(404, "Export folder not found")
    archive = folder / "KTC_clips_and_metadata.zip"
    metadata = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for clip in job.get("clips", []):
            for name in (clip.get("filename"), clip.get("poster")):
                if name and Path(name).name == name and (folder / name).is_file():
                    bundle.write(folder / name, arcname=name)
            item = {key: clip.get(key) for key in (
                "filename", "title", "description", "hashtags", "keywords", "hook",
                "hook_breakdown", "reason", "start", "end", "post_time")}
            metadata.append(item)
            json_name = f"{Path(clip.get('filename', 'clip')).stem}_metadata.json"
            bundle.writestr(json_name, json.dumps(item, ensure_ascii=False, indent=2))
        bundle.writestr("all_clip_metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        bundle.writestr("README.txt", "Review every video and its metadata before posting. KTC does not guarantee reach.\n")
    return FileResponse(archive, media_type="application/zip", filename=archive.name)


@app.get("/api/youtube/status")
def youtube_status() -> dict[str, Any]:
    if not TOKEN_FILE.exists():
        return {"connected": False, "channel": None, "message": "YouTube is not connected."}
    try:
        response = _youtube().channels().list(part="snippet", mine=True).execute()
        items = response.get("items", [])
        if not items:
            return {"connected": False, "channel": None, "message": "No YouTube channel was returned."}
        channel = items[0]
        thumbs = channel.get("snippet", {}).get("thumbnails", {})
        image = thumbs.get("default", {}).get("url")
        return {"connected": True, "channel": {"id": channel["id"],
                "name": channel.get("snippet", {}).get("title", "YouTube channel"),
                "image": image}, "message": "Channel connected."}
    except HTTPException as exc:
        if exc.status_code == 401:
            return {"connected": False, "channel": None, "message": exc.detail}
        raise


@app.post("/api/youtube/connect")
def youtube_connect() -> dict[str, str]:
    if not CLIENT_FILE.is_file():
        raise HTTPException(503, "Add your Google OAuth client file as client_secrets.json. See README for setup.")
    try:
        from google_auth_oauthlib.flow import Flow
        state = secrets.token_urlsafe(32)
        flow = Flow.from_client_secrets_file(str(CLIENT_FILE), scopes=OAUTH_SCOPES, state=state)
        flow.redirect_uri = REDIRECT_URI
        url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
        with state_lock:
            oauth_states.add(state)
        return {"url": url}
    except Exception as exc:
        raise HTTPException(503, f"Could not start Google sign-in: {exc}") from exc


@app.get("/oauth/callback", response_class=HTMLResponse)
def youtube_callback(code: str = Query(default=""), state: str = Query(default=""), error: str = Query(default="")) -> HTMLResponse:
    if error:
        return HTMLResponse("<h1>YouTube connection cancelled</h1><p>You can close this tab and return to KTC.</p>", status_code=400)
    with state_lock:
        valid_state = state in oauth_states
        oauth_states.discard(state)
    if not valid_state or not code:
        raise HTTPException(400, "Invalid or expired OAuth state. Start connecting again from KTC.")
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_secrets_file(str(CLIENT_FILE), scopes=OAUTH_SCOPES, state=state)
        flow.redirect_uri = REDIRECT_URI
        flow.fetch_token(code=code)
        TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")
        return HTMLResponse("<h1>YouTube connected</h1><p>Return to KTC. You may close this tab.</p>")
    except Exception as exc:
        raise HTTPException(400, f"Google sign-in failed: {exc}") from exc


@app.post("/api/youtube/disconnect")
def youtube_disconnect() -> dict[str, str]:
    TOKEN_FILE.unlink(missing_ok=True)
    return {"message": "YouTube disconnected from this local app."}


@app.post("/api/trends")
def research_trends(body: TrendRequest) -> dict[str, Any]:
    """Fetch recent popular videos for a topic using the official YouTube Data API."""
    try:
        params = {"part": "snippet", "q": body.topic, "type": "video", "order": "viewCount",
                  "publishedAfter": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z"),
                  "maxResults": 12, "regionCode": "IN", "key": body.api_key}
        response = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=20)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, "YouTube trend search failed. Check the API key and quota.")
        items = response.json().get("items", [])
        ids = [item.get("id", {}).get("videoId") for item in items]
        ids = [value for value in ids if value]
        stats = {}
        if ids:
            detail = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "statistics,contentDetails", "id": ",".join(ids), "key": body.api_key}, timeout=20)
            detail.raise_for_status()
            stats = {item["id"]: item for item in detail.json().get("items", [])}
        results = []
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
            snippet = item.get("snippet", {})
            results.append({"title": snippet.get("title"), "channel": snippet.get("channelTitle"),
                            "published_at": snippet.get("publishedAt"),
                            "views": stats.get(video_id, {}).get("statistics", {}).get("viewCount"),
                            "url": f"https://www.youtube.com/shorts/{video_id}"})
        return {"topic": body.topic, "region": "IN", "lookback_days": 30, "results": results,
                "note": "Recent popular-video examples, not private Studio Research data. Popularity does not guarantee future views; use as inspiration, not a template."}
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(502, f"Trend lookup failed: {exc}") from exc


@app.get("/api/youtube/analytics")
def youtube_analytics() -> dict[str, Any]:
    return {"available": False,
            "message": "YouTube's audience activity heatmap is not available from the standard YouTube Analytics API. Use YouTube Studio Analytics to check viewer activity. KTC does not invent a channel-specific best time."}


@app.post("/api/youtube/schedule")
def schedule_upload(body: ScheduleRequest) -> dict[str, Any]:
    if not body.approved:
        raise HTTPException(400, "Explicit approval is required before scheduling.")
    if body.job_id not in jobs:
        raise HTTPException(404, "Clip job not found. Keep KTC running until scheduled uploads finish.")
    if not body.job_id.isalnum() or Path(body.filename).name != body.filename:
        raise HTTPException(400, "Invalid clip file reference.")
    clip = next((c for c in jobs[body.job_id].get("clips", []) if c.get("filename") == body.filename), None)
    file_path = (EXPORTS / body.job_id / body.filename).resolve()
    if not clip or EXPORTS.resolve() not in file_path.parents or not file_path.is_file():
        raise HTTPException(404, "Rendered clip not found.")
    scheduled = body.scheduled_at
    if scheduled.tzinfo is None:
        raise HTTPException(422, "Schedule time must include a timezone. Use an IST offset such as +05:30.")
    if scheduled.astimezone(timezone.utc) < datetime.now(timezone.utc) + timedelta(minutes=10):
        raise HTTPException(422, "Choose a future time at least 10 minutes from now.")
    local = scheduled.astimezone(IST)
    if local.hour < 12:
        raise HTTPException(422, "KTC schedules only after 12:00 PM IST.")
    history = _schedule_history()
    channel_id = None
    try:
        youtube = _youtube()
        channel_items = youtube.channels().list(part="id", mine=True).execute().get("items", [])
        channel_id = channel_items[0]["id"] if channel_items else None
        if not channel_id:
            raise HTTPException(401, "No connected YouTube channel found.")
        for old in history:
            if old.get("channel_id") != channel_id or old.get("status") != "scheduled":
                continue
            old_time = datetime.fromisoformat(old["scheduled_at"])
            old_local = old_time.astimezone(IST)
            if old_local.date() == local.date():
                raise HTTPException(409, "Only one upload per IST calendar day. Choose another date.")
            if abs((scheduled.astimezone(timezone.utc) - old_time.astimezone(timezone.utc)).total_seconds()) < 86400:
                raise HTTPException(409, "Leave at least 24 hours between scheduled uploads.")
        description = body.description.strip()
        tags = [tag.lstrip("#").strip() for tag in body.hashtags if tag.strip()]
        snippet = {"title": body.title.strip(), "description": description,
                   "categoryId": "22", "tags": tags[:20]}
        publish_at = scheduled.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        from googleapiclient.http import MediaFileUpload
        response = youtube.videos().insert(
            part="snippet,status",
            body={"snippet": snippet, "status": {"privacyStatus": "private", "publishAt": publish_at,
                                                    "selfDeclaredMadeForKids": False}},
            media_body=MediaFileUpload(str(file_path), mimetype="video/mp4", resumable=True),
        ).execute()
        record = {"channel_id": channel_id, "video_id": response["id"],
                  "scheduled_at": scheduled.isoformat(), "status": "scheduled", "filename": body.filename}
        history.append(record)
        SCHEDULE_FILE.write_text(json.dumps(history, indent=2), encoding="utf-8")
        return {"status": "scheduled", "video_id": response["id"],
                "url": f"https://www.youtube.com/watch?v={response['id']}",
                "scheduled_at_ist": local.isoformat(), "message": "YouTube accepted the scheduled upload."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"YouTube upload or scheduling failed: {exc}") from exc


@app.get("/download/{job_id}/{filename}")
def download(job_id: str, filename: str) -> FileResponse:
    if not job_id.isalnum() or not filename or Path(filename).name != filename:
        raise HTTPException(400, "Invalid download path.")
    folder = (EXPORTS / job_id).resolve()
    path = (folder / filename).resolve()
    if folder not in path.parents or not path.is_file():
        raise HTTPException(404, "File not found.")
    return FileResponse(path, filename=path.name)
