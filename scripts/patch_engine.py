from pathlib import Path

ROOT = Path(".engine")
chat_file = ROOT / "core/api/agnes_chat.py"
limiter_file = ROOT / "core/api/rate_limiter.py"
creative_file = ROOT / "core/pipelines/creative_video.py"
video_file = ROOT / "core/api/agnes_video.py"


def replace_once(path: Path, old: str, new: str):
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"Expected exactly one match in {path}: {old!r}; found {count}"
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {old.strip()} -> {new.strip()}", flush=True)


for required in (chat_file, limiter_file, creative_file, video_file):
    if not required.exists():
        raise SystemExit(f"Upstream file not found: {required}; engine layout may have changed.")

# Agnes Chat: exactly one HTTP attempt; no retry for 429, 5xx, timeout, or connection errors.
replace_once(chat_file, "_MAX_RETRIES = 3", "_MAX_RETRIES = 1")
replace_once(
    chat_file,
    "_RETRY_BASE_DELAY = 15  # 秒，指数退避基数",
    "_RETRY_BASE_DELAY = 0  # retries disabled",
)
# Disable the second chat call previously used after JSON parsing failure.
replace_once(chat_file, "for retry in range(2):", "for retry in range(1):")
replace_once(chat_file, "if retry == 0:", "if retry == 0 and _MAX_RETRIES > 1:")

# Log request start, response status and elapsed time; never print auth headers or prompts.
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

# Creative pipeline: do not retry scene-configuration LLM failures.
replace_once(creative_file, "_MAX_RETRIES = 3", "_MAX_RETRIES = 1")

# Agnes video: one attempt for image upload and video submission; polling errors fail immediately.
replace_once(video_file, "max_retries: int = 5", "max_retries: int = 1")
replace_once(
    video_file,
    "async def _upload_image_to_url(self, image_path: str, retries: int = 3)",
    "async def _upload_image_to_url(self, image_path: str, retries: int = 1)",
)
replace_once(video_file, "max_consecutive_failures: int = 10", "max_consecutive_failures: int = 1")

# Conservative rate limit; this spaces requests but never repeats a failed request.
replace_once(
    limiter_file,
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))',
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "5"))',
)
replace_once(limiter_file, "max_burst: int = 4", "max_burst: int = 1")

print(
    "Agnes patch applied: retries disabled for chat, scene config, image upload, "
    "video submission, and failed polling requests; diagnostics enabled.",
    flush=True,
)
