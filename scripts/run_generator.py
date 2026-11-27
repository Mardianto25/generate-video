import json
import os
import sys
import time
from datetime import datetime, timezone
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


def log(message):
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    print(f"[{now}] {message}", flush=True)


if not IDEA:
    raise SystemExit("VIDEO_IDEA is required")
if not 1 <= SCENE_COUNT <= 10:
    raise SystemExit("SCENE_COUNT must be between 1 and 10")
if SCENE_DURATION not in (5, 10, 15, 18, 20):
    raise SystemExit("SCENE_DURATION must be one of: 5, 10, 15, 18, 20")


def wait_for_server():
    log(f"Waiting for generator server at {BASE_URL}")
    for attempt in range(1, 61):
        try:
            response = requests.get(f"{BASE_URL}/api/config", timeout=5)
            if response.ok:
                log(f"Generator server ready (HTTP {response.status_code})")
                return
            log(f"Server readiness check {attempt}/60 returned HTTP {response.status_code}")
        except requests.RequestException as exc:
            log(f"Server readiness check {attempt}/60 failed: {type(exc).__name__}: {exc}")
        time.sleep(2)
    raise RuntimeError("Generator server did not become ready")


def main():
    started_at = time.monotonic()
    total_duration = SCENE_COUNT * SCENE_DURATION
    log(
        f"Starting generation: scenes={SCENE_COUNT}, scene_duration={SCENE_DURATION}s, "
        f"target_duration={total_duration}s, narration={AUDIO_ENABLED}, "
        f"voice={AUDIO_VOICE}, chaining={CHAINING_MODE}, timeout={TIMEOUT_SECONDS}s"
    )
    log(f"Idea: {IDEA}")
    log(f"Style: {STYLE}")

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

    log("Submitting creative video task (single submission; no automatic resubmission)")
    submit_started = time.monotonic()
    response = requests.post(
        f"{BASE_URL}/api/tasks/creative",
        data=payload,
        timeout=60,
    )
    log(f"Task submission returned HTTP {response.status_code} in {time.monotonic() - submit_started:.1f}s")
    response.raise_for_status()
    result = response.json()
    task_id = result.get("task_id")
    if not task_id:
        raise RuntimeError(f"Generator did not return task_id: {json.dumps(result, ensure_ascii=False)[:2000]}")

    log(f"Generation task created: {task_id}")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_status = None
    poll_count = 0
    last_detail_log = 0.0

    while time.monotonic() < deadline:
        poll_started = time.monotonic()
        status_response = requests.get(f"{BASE_URL}/api/tasks/{task_id}", timeout=30)
        poll_elapsed = time.monotonic() - poll_started
        status_response.raise_for_status()
        state = status_response.json()
        status = str(state.get("status", "unknown")).lower()
        poll_count += 1
        elapsed = time.monotonic() - started_at

        if status != last_status:
            log(f"Task status changed: {last_status or 'initial'} -> {status} (elapsed={elapsed:.1f}s)")
            last_status = status

        # Emit state details every 30 seconds so Actions logs show whether work is progressing.
        if elapsed - last_detail_log >= 30 or poll_count == 1:
            log(
                f"Task heartbeat: poll={poll_count}, status={status}, "
                f"elapsed={elapsed:.1f}s, poll_request={poll_elapsed:.1f}s, "
                f"state={json.dumps(state, ensure_ascii=False)[:1800]}"
            )
            last_detail_log = elapsed

        if status == "completed":
            log(f"Task completed after {elapsed:.1f}s")
            break
        if status == "failed":
            raise RuntimeError(
                "Video generation failed. Task state: "
                + json.dumps(state, ensure_ascii=False)[:4000]
            )
        time.sleep(15)
    else:
        raise TimeoutError(f"Video generation exceeded {TIMEOUT_SECONDS} seconds")

    log("Downloading generated MP4")
    download_started = time.monotonic()
    video_response = requests.get(f"{BASE_URL}/api/video/{task_id}", timeout=300)
    log(
        f"Video download returned HTTP {video_response.status_code} "
        f"in {time.monotonic() - download_started:.1f}s"
    )
    video_response.raise_for_status()

    output = Path("output/generated-video.mp4")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(video_response.content)

    if not output.exists() or output.stat().st_size < 1024:
        raise RuntimeError("Downloaded video is missing or unexpectedly small")

    log(f"Video saved: {output} ({output.stat().st_size:,} bytes)")
    log(f"Total runner elapsed time: {time.monotonic() - started_at:.1f}s")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"FATAL: {type(exc).__name__}: {exc}")
        raise
