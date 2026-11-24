from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from prompts import PRESETS, SYSTEM_PROMPT, user_prompt

BASE = Path(__file__).resolve().parent
CACHE, EXPORTS = BASE / "cache", BASE / "exports"
for folder in (CACHE, EXPORTS, BASE / "fonts", BASE / "music", BASE / "sfx"):
    folder.mkdir(parents=True, exist_ok=True)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


def _which(name: str) -> str | None:
    return shutil.which(name)


def health() -> dict[str, Any]:
    try:
        import faster_whisper  # noqa: F401
        whisper = True
    except Exception:
        whisper = False
    try:
        import cv2
        face = (Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml").is_file()
    except Exception:
        face = False
    return {"tools": {"yt-dlp": _which("yt-dlp") is not None, "faster-whisper": whisper,
                      "ffmpeg": _which("ffmpeg") is not None, "face-detect": face,
                      "caption-fonts": any((BASE / "fonts").glob("*.ttf"))}}


def ollama_models() -> list[str]:
    try:
        r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
        r.raise_for_status()
        return [x["name"] for x in r.json().get("models", [])]
    except Exception:
        return []


def _source(source: str) -> tuple[Path, str, dict[str, Any]]:
    local = Path(source).expanduser()
    if local.is_file():
        local = local.resolve()
        st = local.stat()
        key = _hash(f"{local}:{st.st_size}:{st.st_mtime_ns}")
        target = CACHE / f"{key}{local.suffix.lower()}"
        if not target.exists():
            shutil.copy2(local, target)
        return target, key, {"title": local.stem, "heatmap": []}
    parsed = urlparse(source)
    if parsed.scheme not in {"https", "http"} or not (parsed.hostname == "youtu.be" or (parsed.hostname or "").endswith("youtube.com")):
        raise ValueError("Enter a YouTube URL or a readable local video file path.")
    key = _hash(source)
    video, meta = CACHE / f"{key}.mp4", CACHE / f"{key}.json"
    if video.exists() and meta.exists():
        return video, key, json.loads(meta.read_text(encoding="utf-8"))
    try:
        import yt_dlp
    except Exception as exc:
        raise RuntimeError("Missing yt-dlp. Install requirements.txt again.") from exc
    options = {"format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]", "merge_output_format": "mp4",
               "outtmpl": str(CACHE / f"{key}.%(ext)s"), "quiet": True, "no_warnings": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(options) as client:
        info = client.extract_info(source, download=True)
    files = list(CACHE.glob(f"{key}*.mp4"))
    if not files:
        raise RuntimeError("yt-dlp did not create an MP4. Check FFmpeg and the YouTube URL.")
    data = {"title": info.get("title", "Video"), "heatmap": info.get("heatmap") or []}
    meta.write_text(json.dumps(data), encoding="utf-8")
    return files[0], key, data


def _transcribe(video: Path, key: str, size: str) -> list[dict[str, Any]]:
    path = CACHE / f"{key}.transcript.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data:
                return data
        except (OSError, json.JSONDecodeError):
            pass
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise RuntimeError("Missing faster-whisper. Install requirements.txt again.") from exc
    device, compute = "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            device, compute = "cuda", "float16"
    except Exception:
        pass
    model = WhisperModel(size, device=device, compute_type=compute)
    segments, _ = model.transcribe(str(video), word_timestamps=True, vad_filter=True)
    words = [{"start": float(w.start), "end": float(w.end), "word": w.word.strip()}
             for segment in segments for w in (segment.words or []) if w.word.strip()]
    if not words:
        raise RuntimeError("No speech detected in the source video.")
    path.write_text(json.dumps(words), encoding="utf-8")
    return words


def _duration(video: Path) -> float:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(video)], check=True, capture_output=True, text=True, timeout=30)
    return max(.1, float(result.stdout.strip()))


def _heatmap(points: list[Any]) -> str:
    result = []
    for p in points:
        if isinstance(p, dict):
            try:
                result.append(f"{float(p.get('start_time', p.get('time', 0))):.1f}s={float(p.get('value', p.get('intensity', 0))):.2f}")
            except (TypeError, ValueError):
                pass
    return ", ".join(result[:400])


def _ai(data: dict[str, Any], prompt: str) -> list[dict[str, Any]]:
    if data["ai"] == "ollama":
        r = requests.post("http://127.0.0.1:11434/api/chat", json={"model": data["ollama_model"], "format": "json", "stream": False,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}]}, timeout=600)
        r.raise_for_status()
        text = r.json()["message"]["content"]
    elif data["ai"] == "gemini":
        model = data["gemini_model"].strip() or "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={data['gemini_key']}"
        r = requests.post(url, json={"systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]}, "contents": [{"parts": [{"text": prompt}]},],
            "generationConfig": {"responseMimeType": "application/json"}}, timeout=300)
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    else:
        return []
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    obj = json.loads(text[text.find("{"):text.rfind("}") + 1])
    return obj.get("clips", [])


def _selection(candidates: list[dict[str, Any]], words: list[dict[str, Any]], duration: float, count: int) -> list[dict[str, Any]]:
    valid = []
    for c in candidates:
        try:
            start, end = max(0, float(c["start"])), min(duration, float(c["end"]))
            if end <= start:
                continue
            sw = [w for w in words if abs(w["start"] - start) < 2]
            ew = [w for w in words if abs(w["end"] - end) < 2]
            if sw: start = min(sw, key=lambda w: abs(w["start"] - start))["start"]
            if ew: end = min(ew, key=lambda w: abs(w["end"] - end))["end"]
            inside = [w for w in words if start <= w["start"] and w["end"] <= end]
            if end - start < 8 or len(inside) < 5: continue
            spoken = " ".join(w["word"] for w in inside).lower()
            hook = str(c.get("hook", ""))
            if hook.lower() not in spoken: hook = " ".join(w["word"] for w in inside[:12])
            tags = c.get("hashtags", [])
            valid.append({"start": start, "end": end, "score": max(0, min(100, int(float(c.get("virality_score", 50))))),
                "hook": hook, "why": str(c.get("hook_breakdown", "")), "title": str(c.get("title", "Video highlight"))[:69],
                "hashtags": tags[:5] if isinstance(tags, list) else [], "keywords": c.get("keywords", []) if isinstance(c.get("keywords", []), list) else [],
                "reason": str(c.get("reason", ""))})
        except (ValueError, TypeError, KeyError):
            continue
    chosen = []
    for clip in sorted(valid, key=lambda x: x["score"], reverse=True):
        if all(clip["end"] <= x["start"] or clip["start"] >= x["end"] for x in chosen):
            chosen.append(clip)
        if len(chosen) >= count: break
    return sorted(chosen, key=lambda x: x["start"])


def _heuristic(words: list[dict[str, Any]], duration: float, count: int, label: str) -> list[dict[str, Any]]:
    lo, hi = {"15-30": (15, 30), "30-60": (30, 60), "60-90": (60, 90)}[label]
    span = min(duration, max(lo, min(hi, 45)))
    step = max(span * .7, 8)
    starts = [0] if duration <= span else [i * step for i in range(math.ceil((duration - span) / step) + 1)]
    clips = []
    for start in starts:
        end = min(duration, start + span)
        part = [w for w in words if start <= w["start"] and w["end"] <= end]
        if len(part) < 10: continue
        text = " ".join(w["word"] for w in part)
        tokens = [w["word"].lower().strip(".,!?") for w in part]
        hits = sum(t in {"why", "secret", "never", "wrong", "money", "because", "mistake", "truth", "best", "worst", "stop"} for t in tokens)
        score = min(92, int(35 + min(25, len(part) / max(end - start, 1) * 2) + hits * 2))
        clips.append({"start": start, "end": end, "score": score, "hook": " ".join(w["word"] for w in part[:12]),
                      "why": "Transcript-based opening selected; review for context.", "title": " ".join(text.split()[:8])[:69],
                      "hashtags": ["#shorts", "#highlights", "#video", "#ideas", "#ktc"], "keywords": [], "reason": "Heuristic score from speech density and emphasis words."})
    chosen = []
    for c in sorted(clips, key=lambda x: x["score"], reverse=True):
        if all(c["end"] <= x["start"] or c["start"] >= x["end"] for x in chosen): chosen.append(c)
        if len(chosen) >= count: break
    return sorted(chosen, key=lambda x: x["start"])


def _ass(path: Path, words: list[dict[str, Any]], color: str, font: str) -> None:
    hex_color = color.lstrip("#") if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "C6FF00"
    ass_color = f"&H00{hex_color[4:6]}{hex_color[2:4]}{hex_color[:2]}&"
    face = "Anton" if font == "Anton" else "Montserrat ExtraBold"
    header = f"""[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{face},68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,1,5,2,2,80,170,550,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
    rows = []
    def stamp(t: float) -> str:
        cs = max(0, int(t * 100)); return f"{cs//360000}:{(cs//6000)%60:02d}:{(cs//100)%60:02d}.{cs%100:02d}"
    for i in range(0, len(words), 4):
        part = words[i:i+4]; text = " ".join((r"{\c"+ass_color+"}" if w.get("key") else "")+w["word"].replace("{", "").replace("}", "") for w in part)
        if part: rows.append(f"Dialogue: 0,{stamp(part[0]['start'])},{stamp(max(part[-1]['end'],part[0]['start']+.1))},Default,,0,0,0,,{text}")
    path.write_text(header + "\n".join(rows), encoding="utf-8")


def _render(source: Path, clip: dict[str, Any], words: list[dict[str, Any]], data: dict[str, Any], job_id: str, number: int, job: dict[str, Any]) -> dict[str, Any]:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg: raise RuntimeError("FFmpeg is missing; install it and restart KTC.")
    start, end = clip["start"], clip["end"]
    selected = [w for w in words if start <= w["start"] and w["end"] <= end]
    if data["remove_pauses"]:
        selected = [w for i, w in enumerate(selected) if w["word"].lower().strip(".,!? ") not in {"um", "uh", "erm", "er", "hmm"}]
    outdir = EXPORTS / job_id; outdir.mkdir(parents=True, exist_ok=True)
    ass_path = outdir / f"clip_{number:02d}.ass"
    remapped = [{"start": max(0, w["start"] - start), "end": max(.1, w["end"] - start), "word": w["word"],
                 "key": w["word"].strip(".,!?").lower() in {str(k).lower() for k in clip["keywords"]}} for w in selected]
    _ass(ass_path, remapped, data["color"], data["font"])
    escaped = str(ass_path.resolve()).replace("\\", "/").replace(":", r"\:")
    output = outdir / f"clip_{number:02d}.mp4"
    log = outdir / f"clip_{number:02d}.ffmpeg.log"
    filters = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30,eq=contrast=1.04:saturation=1.06,subtitles='{escaped}'"
    command = [ffmpeg,"-y","-ss",f"{start:.3f}","-i",str(source),"-t",f"{end-start:.3f}","-vf",filters,"-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-af","highpass=f=80,acompressor=threshold=-18dB:ratio=2.5,loudnorm=I=-14:TP=-1.5: LRA=11","-movflags","+faststart","-progress","pipe:1","-nostats",str(output)]
    command[command.index("-af") + 1] = "highpass=f=80,acompressor=threshold=-18dB:ratio=2.5,loudnorm=I=-14:TP=-1.5:LRA=11"
    with log.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            if line.startswith("out_time_ms="):
                try: job["progress"] = min(98, int(int(line.split("=",1)[1])/1_000_000/max(end-start,.1)*100))
                except ValueError: pass
        code = proc.wait()
    if code:
        raise RuntimeError(f"FFmpeg failed; read {log.name} in this job's export folder.")
    poster = outdir / f"clip_{number:02d}.jpg"
    subprocess.run([ffmpeg,"-y","-ss","0.5","-i",str(output),"-frames:v","1","-q:v","3",str(poster)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
    tags = clip["hashtags"] or ["#shorts", "#video"]
    description = f"{clip['title']}\n\n{clip['why']}\n\n{' '.join(tags)}"
    return {"filename": output.name, "poster_url": f"/download/{job_id}/{poster.name}", "url": f"/download/{job_id}/{output.name}",
            "start": start, "end": end, "duration": end-start, "virality_score": clip["score"], "hook": clip["hook"],
            "hook_breakdown": clip["why"], "title": clip["title"], "description": description, "hashtags": tags,
            "reason": clip["reason"], "cuts": 0, "fillers_removed": 0, "broll_count": 0,
            "post_time": "Use your YouTube Studio audience analytics. KTC does not predict guaranteed reach."}


def process_job(job_id: str, data: dict[str, Any], jobs: dict[str, dict[str, Any]]) -> None:
    job = jobs[job_id]
    if not _which("ffmpeg") or not _which("ffprobe"):
        raise RuntimeError("Engine not ready, missing: FFmpeg and ffprobe")
    job.update(status="running", step=1, progress=2, message="Fetching source video")
    source, key, meta = _source(data["source"])
    duration = _duration(source)
    job.update(step=2, progress=10, message="Transcribing word timestamps; first model run downloads weights")
    words = _transcribe(source, key, data["whisper"])
    job.update(step=3, progress=25, message="Finding hooks and replay peaks")
    lo, hi = {"15-30": (15,30), "30-60": (30,60), "60-90": (60,90)}[data["length"]]
    chosen = []
    if data["ai"] != "heuristic":
        try:
            chunks = [words[i:i+2800] for i in range(0,len(words),2800)] if data["ai"] == "ollama" else [words]
            candidates = []
            for chunk in chunks:
                transcript = " ".join(f"[{w['start']:.2f}-{w['end']:.2f}] {w['word']}" for w in chunk)
                candidates.extend(_ai(data,user_prompt(data["preset"],data["custom"],data["count"],lo,hi,transcript,_heatmap(meta.get("heatmap",[])))))
            chosen = _selection(candidates,words,duration,data["count"])
        except Exception as exc:
            job["warnings"].append(f"AI unavailable; using local heuristic. {exc}")
    if not chosen:
        chosen = _heuristic(words,duration,data["count"],data["length"])
        if data["ai"] != "heuristic": job["warnings"].append("AI did not return usable moments; local heuristic selection was used.")
    if not chosen: raise RuntimeError("No suitable spoken clips were found in this video.")
    job.update(step=4, progress=30, message="Rendering vertical clips and captions")
    for i, clip in enumerate(chosen,1):
        rendered = _render(source,clip,words,data,job_id,i,job)
        job["clips"].append(rendered)
        job.update(progress=min(95,30+int(i/len(chosen)*65)),message=f"Clip {i} of {len(chosen)} ready")
    job.update(status="done",step=5,progress=100,message="Clips ready for your review")
