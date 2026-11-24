# KTC Studio — local clipping and YouTube publishing assistant

KTC runs on your own computer. It can download a YouTube video or use a local file, transcribe speech, suggest clips, render portrait videos with captions, and prepare per-clip metadata. Optional features can search recent popular YouTube videos by topic through the official Data API and, after Google OAuth setup and your explicit approval, upload a clip as a private scheduled YouTube video.

KTC cannot promise viral reach. Trend examples are inspiration only. YouTube's private Studio Research data and its viewer-activity heatmap are not exposed through the standard public APIs used here. Use YouTube Studio Analytics for your real audience's activity and performance.

## Run locally

Requirements: Python 3.10+, FFmpeg including `ffprobe`, and disk space for video/model files. Windows: run `setup.bat` (FFmpeg hint: `winget install Gyan.FFmpeg`). macOS/Linux: `chmod +x setup.sh && ./setup.sh` (macOS `brew install ffmpeg`; Debian/Ubuntu `sudo apt install ffmpeg`). Open http://127.0.0.1:8000. Manual start: create a virtual environment, `pip install -r requirements.txt`, then `python -m uvicorn app:app --host 127.0.0.1 --port 8000`.

First Faster-Whisper use downloads model weights. `small` is the default; `base` uses less compute. Compatible CUDA uses float16; CPU uses int8. `cache/` retains downloaded sources and transcripts; `exports/` contains clips and logs.

## AI options

- **Ollama:** install it and run `ollama pull llama3.1` or `ollama pull qwen2.5`; keep the service running.
- **Gemini:** create a key at https://aistudio.google.com/app/apikey. Transcript text is sent to Google when chosen. The browser stores keys in localStorage; do not use a shared computer.
- **Simple selection:** local heuristic fallback, less context-aware.

## Trends

The official YouTube Data API can return recent, popular public video examples for a topic, region, and time window. It does not expose private YouTube Studio Research or the “when your viewers are on YouTube” heatmap through this app. A Data API key and quota are required for trend search. Do not copy other creators; use references to inform original ideas. The app does not fetch or embed trending music. Use audio licensed within YouTube Shorts or media you have rights to; adding a sound inside YouTube after upload is a separate workflow.

## YouTube channel connection and scheduled uploads

Publishing is off until you configure OAuth and approve each upload. KTC never asks for your Google password; Google handles sign-in. To enable it:

1. Create a Google Cloud project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen for your account and add your account as a test user if the app remains in testing.
3. Create an OAuth client of type **Desktop app** or **Web application**. For a Web application, add `http://127.0.0.1:8000/oauth/callback` as an authorized redirect URI.
4. Download the OAuth client JSON to the project root as `client_secrets.json`. Never commit this file. `.gitignore` excludes it.
5. Install the dependencies with `pip install -r requirements.txt`, restart KTC, and use the channel connect control when shown in the app.

The local API supports OAuth, channel name/avatar lookup, disconnect, an explicit `approved: true` schedule-upload request, and a ZIP bundle of clips plus JSON metadata. Scheduled publishing uses YouTube's official upload API: videos are uploaded private with a future `publishAt` timestamp. KTC checks the requested IST time is after noon, no second scheduled upload falls on the same IST date, and uploads are at least 24 hours apart. The server must remain running during the upload. Google may restrict API projects or require verification; quota, OAuth review, account eligibility, and YouTube policies apply. Always verify the schedule in YouTube Studio. If approval or API permissions are missing, the upload fails without being represented as successful.

Available analytics are limited. The API does not provide the Studio “When your viewers are on YouTube” visualization; the current analytics endpoint explicitly reports this limitation rather than fabricating a recommended time. Use YouTube Studio to choose a slot after 12 PM IST. Performance reporting and automatic learning from audience-retention curves are not implemented in this version.

## Current editing limits

Exports are portrait 1080x1920 MP4 with word-timestamp captions and a poster. Per-clip title, description, hashtags, and selection explanation are included. Current rendering uses a simple centered crop, basic voice processing, and the selected caption font/color. It does not yet expose all requested caption controls (font size, outline, shadow, position), provide reliable face tracking, add licensed trending audio, integrate B-roll, or guarantee every pause removal remaps audio and caption timing perfectly. Inspect each clip before posting. The ZIP endpoint includes rendered clips, posters when available, and JSON metadata.

GitHub Pages cannot run Python, FFmpeg, Whisper, OAuth callbacks, or uploads. Free hosting plans may not support video sizes, GPU/CPU needs, long jobs, persistent storage, or Google OAuth restrictions. Keep this personal-use server bound to `127.0.0.1`; it has no public-user authentication. No deployment is performed by this project.

## Troubleshooting and safety

- Verify `ffmpeg -version` and `ffprobe -version` in the same terminal.
- Update yt-dlp with `pip install --upgrade yt-dlp` if YouTube extraction breaks.
- Verify Ollama with `ollama list`.
- Check the per-clip `.ffmpeg.log` in the export directory for render errors.
- FFmpeg needs the `subtitles` filter, usually provided by libass.
- OAuth errors: check the client JSON, exact callback URI, enabled API, consent-screen test user, and local port 8000.
- Trends errors: check Data API key restrictions, enabled API, and quota.

Only download, edit, and publish material you own or are permitted to use. Do not use copyrighted music without permission. A scheduled upload is still a publication decision: review the video and metadata and explicitly approve every schedule request.
