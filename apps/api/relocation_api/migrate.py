"""Tiny forward-only SQL migration runner: numbered .sql files, each applied once."""

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def migrate(database_url: str) -> list[str]:
    """Apply any pending migrations in order. Returns the versions applied."""
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY)")
        # Serialise concurrent startups (several API instances) on one advisory lock.
        conn.execute("SELECT pg_advisory_lock(727001)")
        try:
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations VALUES (%s)", (path.stem,))
                applied.append(path.stem)
        finally:
            conn.execute("SELECT pg_advisory_unlock(727001)")
    return applied


def main() -> int:
    """Run as a Cloud Run job: python -m relocation_api.migrate"""
    import logging
    import os

    logging.basicConfig(level=logging.INFO)
    applied = migrate(os.environ["DATABASE_URL"])
    logging.info("migrations applied: %s", ", ".join(applied) or "none (already up to date)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
