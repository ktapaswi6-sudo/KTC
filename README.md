# KTC Studio — local-first clip editor

KTC is a personal-use local web app for turning a YouTube URL or local video file into portrait captioned clips with suggested titles, descriptions, hashtags, and a posting cadence planner. Local-first processing runs in a FastAPI server on your computer. No deployment has been performed.

## Start

Requirements: Python 3.10+, FFmpeg with `ffprobe`, and disk space for the source plus Whisper model. Windows: run `setup.bat` (FFmpeg install hint: `winget install Gyan.FFmpeg`). macOS/Linux: `chmod +x setup.sh && ./setup.sh` (macOS `brew install ffmpeg`; Debian/Ubuntu `sudo apt install ffmpeg`). Open http://127.0.0.1:8000. Manual start: create and activate a venv, `pip install -r requirements.txt`, then `python -m uvicorn app:app --host 127.0.0.1 --port 8000`.

The first transcription downloads Faster-Whisper model weights. `small` is the default; `base` is lighter and `medium` costs more compute. CPU runs int8; compatible CUDA uses float16.

## AI

Ollama keeps text analysis local. Install Ollama, run `ollama pull llama3.1` or `ollama pull qwen2.5`, start the service, and select the model in KTC. Gemini uses the API key from https://aistudio.google.com/app/apikey; when selected, transcript text is sent to Google. A no-AI heuristic is available and less context-aware. Keys in the UI are stored in browser localStorage, so do not use a shared browser profile. Selection and analysis are suggestions, not guarantees of views.

## Cadence and timing

KTC is an editing tool; it does not connect to YouTube accounts, upload, or schedule posts. The publishing strategy requested for the project is: at least 24 hours between uploads, never two in one calendar day, no catch-up uploads after a missed day, and aim for 3 PM local time. If the planned time has passed and the daily/24-hour rules allow it, publish late rather than skipping. The output metadata is a practical starting point, not a viral guarantee. Best time varies by channel and audience: use YouTube Studio Analytics' audience activity data when available, compare results over several weeks, and treat general posting-time advice as a hypothesis. A first-party API uploader needs a Google Cloud project, YouTube Data API configuration, OAuth consent, quota, and explicit account authorization; it is intentionally not included. Do not share OAuth credentials or authorize an uploader until reviewed.

## Output and limitations

Exports are 1080x1920 H.264/AAC MP4 with burned word-timestamp captions and a poster, plus suggested title, description, hashtags, and moment explanation. Source and transcript cache in `cache/`; exports and FFmpeg logs are in `exports/<job-id>/`. `fonts/`, `music/`, and `sfx/` are reserved for local assets. The current build does not integrate B-roll downloads, music/SFX mixing, advanced speaker tracking, real trend research across Reddit/Instagram, or platform publishing; it does not claim to. YouTube replay heatmap is used when yt-dlp exposes it. Caption and crop behavior depends on your FFmpeg/libass build.

GitHub Pages is static-only and cannot run FFmpeg, Python, Whisper, or the job worker. A free-tier Python service may sleep or lack enough CPU, memory, disk, or job duration. Local use is the reliable target. This server has no login; keep it bound to 127.0.0.1 and do not expose it publicly.

## Troubleshooting

- `ffmpeg -version` and `ffprobe -version` must both work in the same terminal.
- Update a stale extractor with `pip install --upgrade yt-dlp`; some videos may be restricted or unavailable.
- For Ollama, ensure `ollama list` shows the selected model and the server is running.
- Read per-clip `.ffmpeg.log` files under the job export folder on render failures.
- FFmpeg needs the `subtitles` filter (usually libass). Font download may fail offline; system font fallback then applies.
- Faster-Whisper first-run model download requires network access. Select `base` for lower resource use.

Only process and publish material you own or have permission to use. Check platform terms and rights for all music and footage.
