from pathlib import Path

ROOT = Path(".engine")
chat_file = ROOT / "core/api/agnes_chat.py"
limiter_file = ROOT / "core/api/rate_limiter.py"

def replace_once(path: Path, old: str, new: str):
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one match in {path}: {old!r}; found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")
    print(f"Patched {path}: {old.strip()} -> {new.strip()}")

if not chat_file.exists() or not limiter_file.exists():
    raise SystemExit("Upstream Agnes API files were not found; engine layout may have changed.")

# Retry 429 responses for longer, allowing short-lived provider rate limits to clear.
replace_once(chat_file, "_MAX_RETRIES = 3", "_MAX_RETRIES = 5")
replace_once(chat_file, "_RETRY_BASE_DELAY = 15  # 秒，指数退避基数", "_RETRY_BASE_DELAY = 30  # seconds; retry delays: 30, 60, 90, 120")

# Use a conservative shared request rate and disable bursts.
replace_once(limiter_file, '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "20"))',
             '_AGNES_RATE_LIMIT = int(os.environ.get("AGNES_RATE_LIMIT", "5"))')
replace_once(limiter_file, "max_burst: int = 4", "max_burst: int = 1")
print("Agnes rate-limit compatibility patch applied.")
