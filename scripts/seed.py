"""Seed the local database: 8 areas and 12 fake PGs.

Reads DATABASE_URL and PHONE_ENCRYPTION_KEY from the environment or from .env.
Usage:  python scripts/seed.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("apps/api", "packages/schemas/py", "packages/tools/py"):
    sys.path.insert(0, str(ROOT / sub))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


load_dotenv(ROOT / ".env")

from relocation_api.seed import main  # noqa: E402

if __name__ == "__main__":
    main()
