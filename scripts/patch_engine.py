from pathlib import Path

ROOT = Path(".engine")
chat_file = ROOT / "core/api/agnes_chat.py"
limiter_file = ROOT / "core/api/rate_limiter.py"


def replace_once(path: Path, old: str, new: str):
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(
            f"Expected exactly one match in {path}: {old!r}; found {count}"
        )
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {old.strip()} -> {new.strip()}", flush=True)


if not chat_file.exists() or not limiter_file.exists():
    raise SystemExit("Upstream Agnes API files were not found; engine layout may have changed.")

# Exactly one HTTP attempt. No retries for 429, 5xx, timeouts, or connection errors.
replace_once(chat_file, "_MAX_RETRIES = 3", "_MAX_RETRIES = 1")
replace_once(
    chat_file,
    "_RETRY_BASE_DELAY = 15  # 秒，指数退避基数",
    "_RETRY_BASE_DELAY = 0  # retries disabled",
)

# Disable the separate second chat call used when JSON parsing fails.
replace_once(chat_file, "for retry in range(2):", "for retry in range(1):")
replace_once(chat_file, "if retry == 0:", "if retry == 0 and _MAX_RETRIES > 1:")

# Add request timing and HTTP response diagnostics without logging credentials or prompts.
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

# Conservative rate limit; this only spaces requests and does not retry failed calls.
replace_once(
    limiter_file,
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))',
    '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "5"))',
)
replace_once(limiter_file, "max_burst: int = 4", "max_burst: int = 1")

print("Agnes patch applied: one attempt per API call, retries disabled, diagnostics enabled.", flush=True)
