from pathlib import Path

ROOT = Path(".engine")
chat_file = ROOT / "core/api/agnes_chat.py"
limiter_file = ROOT / "core/api/rate_limiter.py"
creative_file = ROOT / "core/pipelines/creative_video.py"
video_file = ROOT / "core/api/agnes_video.py"
image_file = ROOT / "core/api/agnes_image.py"
screenwriter_file = ROOT / "core/screenwriter.py"
tts_file = ROOT / "core/audio/tts.py"
video_utils_file = ROOT / "utils/video.py"
image_utils_file = ROOT / "utils/image.py"


def replace_once(path: Path, old: str, new: str):
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"Expected exactly one match in {path}: {old!r}; found {count}"
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {old.strip()} -> {new.strip()}", flush=True)


required_files = (
    chat_file, limiter_file, creative_file, video_file, image_file,
    screenwriter_file, tts_file, video_utils_file, image_utils_file,
)
for required in required_files:
    if not required.exists():
        raise SystemExit(f"Upstream file not found: {required}; engine layout may have changed.")

# Agnes Chat: exactly one HTTP attempt; no retry for 429, 5xx, timeout, or connection errors.
replace_once(chat_file, "_MAX_RETRIES = 3", "_MAX_RETRIES = 1")
replace_once(
    chat_file,
    "_RETRY_BASE_DELAY = 15  # 秒，指数退避基数",
    "_RETRY_BASE_DELAY = 0  # retries disabled",
)
replace_once(chat_file, "for retry in range(2):", "for retry in range(1):")
replace_once(chat_file, "if retry == 0:", "if retry == 0 and _MAX_RETRIES > 1:")
replace_once(
    chat_file,
    """                resp = requests.post(
                    f"{BASE_URL}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=timeout,
                )
""",
    """                request_started = time.monotonic()
                logger.info(
                    f"[AgnesChat] POST /chat/completions started "
                    f"(attempt {attempt + 1}/{_MAX_RETRIES}, timeout={timeout}s)"
                )
                resp = requests.post(
                    f"{BASE_URL}/chat/completions",
                    headers=self.headers,
                    json=payload,
                    timeout=timeout,
                )
                request_elapsed = time.monotonic() - request_started
                logger.info(
                    f"[AgnesChat] HTTP {resp.status_code} received "
                    f"after {request_elapsed:.1f}s"
                )
""",
)
replace_once(
    chat_file,
    """            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
""",
    """            except (requests.ConnectionError, requests.Timeout) as e:
                logger.exception(
                    f"[AgnesChat] Request failed without retry: {type(e).__name__}"
                )
                last_exc = e
""",
)
replace_once(
    chat_file,
    """                resp.raise_for_status()
                return resp.json()
""",
    """                try:
                    resp.raise_for_status()
                except requests.HTTPError:
                    logger.error(
                        f"[AgnesChat] HTTP request failed: status={resp.status_code}, "
                        f"body={resp.text[:1000]!r}; no retry will be attempted"
                    )
                    raise
                return resp.json()
""",
)

# Creative pipeline: no retry for scene configuration or end-frame generation.
replace_once(creative_file, "_MAX_RETRIES = 3", "_MAX_RETRIES = 1")
replace_once(creative_file, "for attempt in range(3):", "for attempt in range(1):")

# Agnes video and image APIs: one attempt only. Polling errors fail immediately.
replace_once(video_file, "max_retries: int = 5", "max_retries: int = 1")
replace_once(
    video_file,
    "async def _upload_image_to_url(self, image_path: str, retries: int = 3)",
    "async def _upload_image_to_url(self, image_path: str, retries: int = 1)",
)
replace_once(video_file, "max_consecutive_failures: int = 10", "max_consecutive_failures: int = 1")
replace_once(image_file, "max_retries: int = 3,", "max_retries: int = 1,")

# Image analysis and TTS also stop on their first failed attempt.
replace_once(
    screenwriter_file,
    "def _describe_with_retry(self, prompt: str, img_path: str, label: str, text_prompt: str = None, max_retries: int = 3)",
    "def _describe_with_retry(self, prompt: str, img_path: str, label: str, text_prompt: str = None, max_retries: int = 1)",
)
replace_once(tts_file, "max_attempts = 2", "max_attempts = 1")

# Disable automatic retries when downloading generated media.
replace_once(video_utils_file, "@retry(stop=stop_after_attempt(3))\n", "")
replace_once(image_utils_file, "@retry(stop=stop_after_attempt(3))\n", "")

# Conservative rate limit; this spaces requests but never repeats a failed request.
replace_once(
    limiter_file,
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))',
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "5"))',
)
replace_once(limiter_file, "max_burst: int = 4", "max_burst: int = 1")

print(
    "No-retry patch applied across Agnes chat/image/video, scene generation, "
    "image analysis, TTS, polling failures, and media downloads. "
    "Request diagnostics enabled.",
    flush=True,
)
