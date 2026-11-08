"""Wait for every local service to report healthy. Exit 1 if any fails."""

import json
import sys
import time
import urllib.request

CHECKS = {
    "api": "http://localhost:8010/health/ready",
    "voice-gateway": "http://localhost:8011/health/ready",
    "worker": "http://localhost:8012/health/ready",
    "web": "http://localhost:3000/api/health",
}
TIMEOUT_SECONDS = 90


def probe(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as res:
            return json.load(res)
    except Exception:
        return None


def main() -> int:
    deadline = time.time() + TIMEOUT_SECONDS
    pending = dict(CHECKS)
    while pending and time.time() < deadline:
        for name, url in list(pending.items()):
            body = probe(url)
            if body is not None:
                print(f"OK    {name}: {body}")
                del pending[name]
        if pending:
            time.sleep(2)
    for name in pending:
        print(f"FAIL  {name}: no healthy response")
    return 1 if pending else 0


if __name__ == "__main__":
    sys.exit(main())
