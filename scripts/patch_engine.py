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
server_file = ROOT / "server.py"


def replace_once(path: Path, old: str, new: str):
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"Expected exactly one match in {path}: {old!r}; found {count}"
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {old.strip()} -> {new.strip()}", flush=True)


def replace_block(path: Path, start_marker: str, end_marker: str, replacement: str):
    source = path.read_text(encoding="utf-8")
    start = source.find(start_marker)
    end = source.find(end_marker, start + len(start_marker))
    if start < 0 or end < 0:
        raise SystemExit(f"Could not locate patch block in {path}: {start_marker!r}")
    path.write_text(source[:start] + replacement + source[end:], encoding="utf-8")
    print(f"Patched model fallback in {path}", flush=True)


required_files = (
    chat_file, limiter_file, creative_file, video_file, image_file,
    screenwriter_file, tts_file, video_utils_file, image_utils_file, server_file,
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
# Use the video model selected from the live /models catalog by preflight.
replace_once(
    creative_file,
    'video_model: str = "agnes-video-v2.0"',
    'video_model: str = os.environ.get("AGNES_VIDEO_MODEL", "agnes-video-2.5-flash")',
)
replace_once(creative_file, "for attempt in range(3):", "for attempt in range(1):")

# Agnes video and image APIs: one attempt only. Polling errors fail immediately.
replace_once(video_file, "max_retries: int = 5", "max_retries: int = 1")

# Replace the upstream retry loop entirely. A failed video submission is logged
# with its HTTP response body and exits immediately: no 429/5xx/timeout retries,
# no frame-reduction resubmissions, and no misleading "retry 1/1" message.
replace_block(
    video_file,
    "    async def _submit_with_retry(",
    "    async def generate_single_video(",
    """    async def _submit_with_retry(self, payload: dict, mode_desc: str) -> str:
        \"\"\"Submit once; expose the exact API failure without retrying.\"\"\"
        if self.shutdown_event and self.shutdown_event.is_set():
            raise RuntimeError("Video generation cancelled by user")

        logger.info(
            f"[AgnesVideo] Submitting {mode_desc} (single attempt; retries disabled)"
        )
        started = time.monotonic()
        try:
            await asyncio.to_thread(get_rate_limiter().acquire)
            resp = await asyncio.wait_for(
                asyncio.to_thread(
                    requests.post,
                    f"{BASE_URL}/videos",
                    headers=self.headers,
                    json=payload,
                    timeout=(15, 60),
                ),
                timeout=90,
            )
        except (requests.exceptions.RequestException, asyncio.TimeoutError) as exc:
            elapsed = time.monotonic() - started
            logger.exception(
                f"[AgnesVideo] Submit transport failure after {elapsed:.1f}s "
                f"({type(exc).__name__}); no retry will be attempted"
            )
            raise RuntimeError(
                f"Agnes video submit transport failure ({type(exc).__name__}); "
                "request was not retried"
            ) from exc

        elapsed = time.monotonic() - started
        response_body = (resp.text or "")[:2000]
        logger.info(
            f"[AgnesVideo] POST /videos -> HTTP {resp.status_code} "
            f"after {elapsed:.1f}s"
        )

        if resp.status_code != 200:
            logger.error(
                f"[AgnesVideo] Video submission rejected: "
                f"HTTP {resp.status_code}; body={response_body!r}; "
                "no retry will be attempted"
            )
            raise RuntimeError(
                f"Agnes video submit failed (HTTP {resp.status_code}): "
                f"{response_body}"
            )

        try:
            result = resp.json()
        except ValueError as exc:
            logger.error(
                f"[AgnesVideo] HTTP 200 returned invalid JSON: {response_body!r}"
            )
            raise RuntimeError("Agnes video submit returned invalid JSON") from exc

        video_id = result.get("video_id") or result.get("task_id") or result.get("id")
        if not video_id:
            logger.error(
                f"[AgnesVideo] HTTP 200 response has no video/task id: "
                f"{response_body!r}"
            )
            raise RuntimeError(
                f"Agnes video submit response missing video id: {response_body}"
            )

        return video_id

"""
)
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

# Keep the conservative API rate limit and burst size.
replace_once(
    limiter_file,
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))',
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "5"))',
)
replace_once(limiter_file, "max_burst: int = 4", "max_burst: int = 1")

# A creative task has weight 3. The old semaphore capacity at rate limit 5 was
# 5 // 2 = 2, so acquire() raised ValueError and left the task stuck as queued.
# Guarantee capacity for at least one task of the heaviest supported type.
replace_once(
    server_file,
    "MAX_CONCURRENT_WEIGHT = _AGNES_RATE_LIMIT // 2  # 默认 10",
    "MAX_CONCURRENT_WEIGHT = max(_AGNES_RATE_LIMIT // 2, max(TASK_TYPE_WEIGHTS.values()))",
)

# Mark unexpected queue/worker errors as failed and never release a slot that
# was not actually acquired (the upstream finally block previously did so).
replace_once(
    server_file,
    """    task_manager.update_state(status=StepStatus.QUEUED)

    try:
        # 等待并发槽位
        await _pipeline_semaphore.acquire(weight)
""",
    """    task_manager.update_state(status=StepStatus.QUEUED)
    acquired = False

    try:
        # 等待并发槽位
        await _pipeline_semaphore.acquire(weight)
        acquired = True
""",
)
replace_once(
    server_file,
    """    except asyncio.CancelledError:
        # 任务被取消（如 stop 操作）
        _queued_tasks.pop(task_id, None)
        logger.info(f"[Concurrency] Task {task_id} cancelled while queued")
    finally:
        # 释放信号量
        try:
            await _pipeline_semaphore.release(weight)
            logger.info(
                f"[Concurrency] Task {task_id} released slot (weight={weight}, "
                f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
            )
        except Exception:
            pass
        _queued_tasks.pop(task_id, None)
""",
    """    except asyncio.CancelledError:
        # 任务被取消（如 stop 操作）
        _queued_tasks.pop(task_id, None)
        logger.info(f"[Concurrency] Task {task_id} cancelled while queued")
    except Exception as e:
        _queued_tasks.pop(task_id, None)
        logger.exception(f"[Concurrency] Task {task_id} failed before/during pipeline execution: {e}")
        task_manager.update_state(status=StepStatus.FAILED)
    finally:
        # Release only when this task actually acquired a semaphore slot.
        if acquired:
            try:
                await _pipeline_semaphore.release(weight)
                logger.info(
                    f"[Concurrency] Task {task_id} released slot (weight={weight}, "
                    f"current={_pipeline_semaphore.current}/{_pipeline_semaphore.max_weight})"
                )
            except Exception:
                logger.exception(f"[Concurrency] Failed to release slot for task {task_id}")
        _queued_tasks.pop(task_id, None)
""",
)

# Model fallback: try each configured chat model once, in order. This is not a retry
# of the same model; it is a failover to a different model, preserving no-retry policy.
replace_block(
    chat_file,
    "    def _request_with_retry(",
    "    def chat(self,",
    "    def _request_with_retry(self, payload: dict, timeout: int = 120) -> dict:\n        \"\"\"Try configured chat models in order; one HTTP attempt per model.\"\"\"\n        configured = os.environ.get(\n            \"AGNES_CHAT_MODELS\",\n            \"agnes-3.0-flash,agnes-2.5-flash,agnes-2.0-flash\",\n        )\n        models = [item.strip() for item in configured.split(\",\") if item.strip()]\n        if not models:\n            models = [self.model]\n\n        last_error = None\n        for index, model in enumerate(models, start=1):\n            request_payload = dict(payload)\n            request_payload[\"model\"] = model\n            started = time.monotonic()\n            logger.info(\n                f\"[AgnesChat] Trying model {index}/{len(models)}: {model} \"\n                f\"(single attempt, timeout={timeout}s)\"\n            )\n            try:\n                get_rate_limiter().acquire()\n                resp = requests.post(\n                    f\"{BASE_URL}/chat/completions\",\n                    headers=self.headers,\n                    json=request_payload,\n                    timeout=timeout,\n                )\n                elapsed = time.monotonic() - started\n                logger.info(\n                    f\"[AgnesChat] Model {model} returned HTTP {resp.status_code} \"\n                    f\"after {elapsed:.1f}s\"\n                )\n                resp.raise_for_status()\n                data = resp.json()\n                self.model = model\n                if index > 1:\n                    logger.warning(f\"[AgnesChat] Fallback succeeded; active model is now {model}\")\n                return data\n            except (requests.RequestException, ValueError) as exc:\n                last_error = exc\n                logger.error(\n                    f\"[AgnesChat] Model {model} failed: {type(exc).__name__}: {exc}\"\n                )\n                if index < len(models):\n                    logger.warning(\n                        f\"[AgnesChat] Switching to next model: {models[index]}\"\n                    )\n\n        logger.error(\n            f\"[AgnesChat] All configured models failed: {', '.join(models)}\"\n        )\n        if last_error:\n            raise last_error\n        raise RuntimeError(\"No Agnes chat models are configured\")\n\n"
)

print(
    "No-retry patch applied. Chat model failover enabled; semaphore capacity supports "
    "the heaviest task; queue exceptions mark tasks failed; slot release is guarded.",
    flush=True,
)
