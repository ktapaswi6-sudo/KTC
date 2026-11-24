PRESETS = {
    "Viral Hook & Payoff": "Open on a compelling actual spoken line, skip greetings, build toward a clear payoff.",
    "High-Voltage / Intense Debate": "Find energetic debate, contrarian points, surprising evidence, and strong opinions.",
    "Seamless Loop Master": "Find a self-contained moment whose ending can flow naturally back to its opening.",
    "Story & Plot Twist": "Find a story with setup, tension, reveal, or an unexpected reversal.",
    "30-Second Value Bomb": "Find a concise actionable lesson or useful framework; avoid filler.",
    "Aesthetic / Cinematic B-Roll Pace": "Find a thoughtful, visually evocative quote; don't over-cut meaningful pauses.",
    "Savage Roast / Comedy Timing": "Find a real punchline; preserve the pause that makes the joke land.",
    "Most-Replayed / Peak Momentum": "Prioritize available YouTube replay heatmap peaks and transcript moments.",
}
SYSTEM_PROMPT = """You are an honest short-video editor. Select transcript spans with exact absolute timestamps. Return strict JSON only: {\"clips\":[{\"start\":1.0,\"end\":30.0,\"virality_score\":70,\"hook\":\"exact words spoken\",\"hook_breakdown\":\"why this works\",\"title\":\"under 70 chars\",\"hashtags\":[\"#tag1\",\"#tag2\",\"#tag3\",\"#tag4\",\"#tag5\"],\"keywords\":[\"spoken word\"],\"reason\":\"reason\"}]}. Never fabricate or misrepresent speech. Use an honest spread of scores and do not promise virality. Pick self-contained moments near the requested duration, favor strong opening hooks and payoff, and return fewer clips rather than invent times."""

def user_prompt(preset: str, custom: str, count: int, low: int, high: int, transcript: str, heatmap: str) -> str:
    return f"Creative direction: {preset}. {PRESETS[preset]}\nUser direction: {custom or 'None'}\nReturn up to {count} clips of {low}-{high} seconds.\nTimestamped transcript:\n{transcript}\nAvailable YouTube replay heatmap (time=intensity; may be unavailable):\n{heatmap or 'No heatmap available.'}"
