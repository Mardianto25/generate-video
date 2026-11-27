import os
import sys
import time

import requests

BASE_URL = os.getenv("AGNES_BASE_URL", "https://apihub.agnes-ai.com/v1").rstrip("/")
API_KEY = os.environ["AGNES_API_KEY"]
PREFERRED_ORDER = [
    "agnes-3.0-flash",
    "agnes-2.5-flash",
    "agnes-2.0-flash",
]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def log(message):
    print(f"[AgnesPreflight] {message}", flush=True)


def extract_model_ids(payload):
    items = payload.get("data", []) if isinstance(payload, dict) else payload
    if isinstance(items, dict):
        items = items.get("models", [])
    if not isinstance(items, list):
        raise ValueError("Unexpected /models response format")

    ids = []
    for item in items:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = item.get("id") or item.get("name") or item.get("model")
        else:
            model_id = None
        if model_id and isinstance(model_id, str):
            ids.append(model_id)
    return list(dict.fromkeys(ids))


def main():
    log(f"Checking model catalog at {BASE_URL}/models")
    response = requests.get(f"{BASE_URL}/models", headers=HEADERS, timeout=30)
    log(f"GET /models -> HTTP {response.status_code}")
    response.raise_for_status()
    available_ids = extract_model_ids(response.json())
    if not available_ids:
        raise RuntimeError("Agnes returned an empty model catalog")

    # Only probe text/chat models. Prefer the known candidates, then any other
    # catalog entries that look like text models. Image/video models are excluded.
    text_ids = [
        model_id for model_id in available_ids
        if not any(token in model_id.lower() for token in ("image", "video", "embed", "audio", "tts"))
    ]
    ordered = [model_id for model_id in PREFERRED_ORDER if model_id in text_ids]
    ordered.extend(model_id for model_id in text_ids if model_id not in ordered)

    log(f"Catalog contains {len(available_ids)} model(s); {len(ordered)} chat candidate(s)")
    for model_id in available_ids:
        log(f"Catalog model: {model_id}")
    if not ordered:
        raise RuntimeError("No text/chat model candidates found in Agnes model catalog")

    working = []
    for index, model_id in enumerate(ordered, start=1):
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with OK"}],
            "max_tokens": 8,
            "temperature": 0,
        }
        started = time.monotonic()
        log(f"Probe {index}/{len(ordered)}: {model_id}")
        try:
            probe = requests.post(
                f"{BASE_URL}/chat/completions",
                headers=HEADERS,
                json=payload,
                timeout=45,
            )
            elapsed = time.monotonic() - started
            log(f"{model_id}: HTTP {probe.status_code} in {elapsed:.1f}s")
            probe.raise_for_status()
            result = probe.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content")
            if not content:
                raise ValueError("HTTP success but no chat content was returned")
            working.append(model_id)
            log(f"AVAILABLE: {model_id} (response received)")
        except (requests.RequestException, ValueError, KeyError, IndexError) as exc:
            log(f"UNAVAILABLE: {model_id}: {type(exc).__name__}: {exc}")

    if not working:
        raise RuntimeError("None of the listed Agnes chat models passed the live probe")

    selected = ",".join(working)
    log(f"Working model order: {selected}")
    github_env = os.getenv("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as env_file:
            env_file.write(f"AGNES_CHAT_MODELS={selected}\n")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as summary_file:
            summary_file.write("### Agnes chat model preflight\n\n")
            summary_file.write("| Model | Probe result |\n|---|---|\n")
            for model_id in ordered:
                summary_file.write(
                    f"| {model_id} | {'Available' if model_id in working else 'Unavailable'} |\n"
                )
            summary_file.write(f"\n**Fallback order:** {selected}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"FATAL: {type(exc).__name__}: {exc}")
        sys.exit(1)
