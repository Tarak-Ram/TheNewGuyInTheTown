"""Deletes one person's data when they cannot do it themselves in the app.

    python scripts/delete_account.py --email person@example.com --confirm DELETE
    python scripts/delete_account.py --user-id <uuid> --confirm DELETE

It runs exactly the same code as the app's "Delete my account" button, so files, transcripts,
facts, agreements and audio are all removed, and the audit log records it.

Point DATABASE_URL (and DOCUMENT_BUCKET / AUDIO_BUCKET for cloud storage) at the right
environment first. For staging or production, connect through the Cloud SQL Auth Proxy.
"""

import argparse
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


def find_user(conn, email: str | None, user_id: str | None):
    if user_id:
        return conn.execute(
            "SELECT id, email, deleted_at FROM users WHERE id = %s", (user_id,)
        ).fetchone()
    return conn.execute(
        "SELECT id, email, deleted_at FROM users WHERE lower(email) = lower(%s)", (email,)
    ).fetchone()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--email")
    who.add_argument("--user-id")
    parser.add_argument("--confirm", default="", help="Must be DELETE")
    args = parser.parse_args(argv)

    if args.confirm != "DELETE":
        print("Refusing to run: add --confirm DELETE. This cannot be undone.")
        return 2

    load_dotenv(ROOT / ".env")
    import psycopg
    from nguit_tools.storage import get_audio_store, get_store
    from psycopg.rows import dict_row
    from relocation_api.account import erase_user

    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as conn:
        user = find_user(conn, args.email, args.user_id)
        if user is None:
            print("No such user. Nothing was deleted.")
            return 1
        if user["deleted_at"] is not None:
            print("That account is already deleted. Nothing to do.")
            return 0
        result = erase_user(conn, user["id"], get_store(), get_audio_store())
    print(
        f"Deleted: {result.plans} plan(s), {result.calls} call(s), "
        f"{result.agreements} agreement(s)."
    )
    if result.files_pending:
        print(f"{result.files_pending} file(s) could not be deleted yet. The daily job will retry.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
