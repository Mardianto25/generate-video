import json
import os
import sys
import time
from pathlib import Path

import requests

BASE_URL = os.getenv("GENERATOR_URL", "http://127.0.0.1:8765")
IDEA = os.environ["VIDEO_IDEA"].strip()
STYLE = os.getenv("VIDEO_STYLE", "Cinematic realistic 3D animation, emotional storytelling, dramatic lighting")
SCENE_COUNT = int(os.getenv("SCENE_COUNT", "3"))
SCENE_DURATION = int(os.getenv("SCENE_DURATION", "5"))
AUDIO_ENABLED = os.getenv("AUDIO_ENABLED", "true").lower() == "true"
AUDIO_VOICE = os.getenv("AUDIO_VOICE", "id-ID-ArdiNeural")
CHAINING_MODE = os.getenv("CHAINING_MODE", "keyframes")
TIMEOUT_SECONDS = int(os.getenv("GENERATION_TIMEOUT_SECONDS", "21000"))

if not IDEA:
    raise SystemExit("VIDEO_IDEA is required")
if not 1 <= SCENE_COUNT <= 10:
    raise SystemExit("SCENE_COUNT must be between 1 and 10")
if SCENE_DURATION not in (5, 10, 15, 18, 20):
    raise SystemExit("SCENE_DURATION must be one of: 5, 10, 15, 18, 20")

def wait_for_server():
    for _ in range(60):
        try:
            response = requests.get(f"{BASE_URL}/api/config", timeout=5)
            if response.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise RuntimeError("Generator server did not become ready")

def main():
    wait_for_server()

    durations = [SCENE_DURATION] * SCENE_COUNT
    payload = {
        "idea": IDEA,
        "creative_name": "github-actions-video",
        "style": STYLE,
        "negative_prompt": "blurry, low quality, deformed anatomy, inconsistent character, text artifacts, watermark",
        "include_characters": "true",
        "chaining_mode": CHAINING_MODE,
        "video_width": "768",
        "video_height": "1152",
        "duration_source": "manual",
        "scene_count": str(SCENE_COUNT),
        "uniform_duration": "true",
        "scene_durations_json": json.dumps(durations),
        "audio_enabled": str(AUDIO_ENABLED).lower(),
        "audio_voice": AUDIO_VOICE,
        "audio_rate": "+0%",
        "subtitle_enabled": "true",
        "subtitle_style_mode": "fixed",
        "subtitle_font": "DejaVuSans.ttf",
        "subtitle_color": "white",
        "subtitle_fontsize": "42",
        "subtitle_position": "bottom",
        "subtitle_stroke_color": "black",
        "subtitle_stroke_width": "3",
        "subtitle_bg_color": "black@0.35",
    }

    response = requests.post(f"{BASE_URL}/api/tasks/creative", data=payload, timeout=60)
    response.raise_for_status()
    result = response.json()
    task_id = result.get("task_id")
    if not task_id:
        raise RuntimeError(f"Generator did not return task_id: {result}")

    print(f"Generation task created: {task_id}")
    deadline = time.time() + TIMEOUT_SECONDS
    last_status = None

    while time.time() < deadline:
        status_response = requests.get(f"{BASE_URL}/api/tasks/{task_id}", timeout=30)
        status_response.raise_for_status()
        state = status_response.json()
        status = str(state.get("status", "")).lower()
        if status != last_status:
            print(f"Task status: {status}")
            last_status = status

        if status == "completed":
            break
        if status == "failed":
            raise RuntimeError(
                "Video generation failed. Check the preceding Agnes/runner logs. "
                + json.dumps(state, ensure_ascii=False)[:3000]
            )
        time.sleep(15)
    else:
        raise TimeoutError(f"Video generation exceeded {TIMEOUT_SECONDS} seconds")

    video_response = requests.get(f"{BASE_URL}/api/video/{task_id}", timeout=300)
    video_response.raise_for_status()

    output = Path("output/generated-video.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(video_response.content)

    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("Downloaded video is missing or unexpectedly small")

    print(f"Video saved: {output} ({output.stat().st_size:,} bytes)")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
