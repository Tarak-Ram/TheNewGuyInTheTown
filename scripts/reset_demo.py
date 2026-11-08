"""Puts the demo back to a clean starting point, ready for the next run.

    python scripts/reset_demo.py                  # clean slate for the demo account
    python scripts/reset_demo.py --sample-calls   # ...plus 3 pre-recorded sample calls

What it does:
  - deletes the demo account's plans, calls, transcripts, facts and uploaded agreements;
  - restores the 8 sample areas and 12 fake PGs, and gives back any PG's consent that was
    withdrawn during a rehearsal (for example by trying the "please stop calling" moment);
  - with --sample-calls, adds a plan and three finished sample calls whose facts are read from
    their transcripts by the same checks as a live call. They are labelled "Pre-recorded sample"
    on screen. Use them only as the backup when the live voice call is not available.

Safety: it only runs when DEMO_MODE=true, and it only ever touches the demo account
(google_sub = 'demo-user') and the fake sample PGs. It can never touch a real user's data.
"""

import argparse
import os
import subprocess
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

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from relocation_api.demo import DEMO_USER_EMAIL, DEMO_USER_SUB, OFFICES  # noqa: E402
from relocation_api.migrate import migrate  # noqa: E402
from relocation_api.seed import CONSENT_POLICY, seed  # noqa: E402

SEED_PG_PATTERN = r"^TEST PG [0-9]{2} [(]fake[)]$"

OPENING = (
    "Hello, this is an AI assistant from The New Guy in Town, "
    "calling for a person looking for a PG. Is this a good time?"
)

# (PG number, finished-call status, what the owner said). Fake conversations for the backup.
SAMPLE_CALLS = [
    (
        3,
        "completed",
        [
            ("agent", OPENING),
            ("owner", "Yes, go ahead."),
            ("agent", "What is the monthly rent for a bed?"),
            ("owner", "Rent is twelve thousand per month. Deposit is 24000."),
            ("agent", "Is food included?"),
            ("owner", "Breakfast and dinner are included. Notice period is 30 days."),
            ("agent", "And when is a bed available?"),
            ("owner", "Double sharing is available from 1st December. No smoking and no alcohol."),
        ],
    ),
    (
        4,
        "completed",
        [
            ("agent", OPENING),
            ("owner", "Yes."),
            ("agent", "What is the monthly rent?"),
            ("owner", "Around eleven thousand, maybe. I need to check with the owner."),
            ("agent", "And the deposit?"),
            ("owner", "Deposit is two months rent. Triple sharing room is available immediately."),
        ],
    ),
    (
        6,
        "opted_out",
        [
            ("agent", OPENING),
            ("owner", "Rent is 14000."),
            ("agent", "Thank you. Is food included?"),
            ("owner", "Not interested. Please stop calling me."),
        ],
    ),
]


def refuse_unless_demo() -> None:
    if os.environ.get("DEMO_MODE", "").strip().lower() != "true":
        sys.exit("Refusing to run: DEMO_MODE is not 'true'. This command is for the demo only.")


def delete_uploaded_files(keys: list[str]) -> None:
    """Agreement files live in the API container's volume, so remove them there."""
    for key in keys:
        local = Path(os.environ.get("AGREEMENT_STORAGE_DIR", "./data/agreements")) / key
        local.unlink(missing_ok=True)
        subprocess.run(
            ["docker", "compose", "exec", "-T", "api", "rm", "-f", f"/data/agreements/{key}"],
            cwd=ROOT, capture_output=True, check=False,
        )  # fmt: skip


def wipe_demo_user(conn: psycopg.Connection) -> dict[str, int]:
    user = conn.execute("SELECT id FROM users WHERE google_sub = %s", (DEMO_USER_SUB,)).fetchone()
    if user is None:
        return {"plans": 0, "agreements": 0}
    uid = user["id"]
    plans = [r["id"] for r in conn.execute("SELECT id FROM move_plans WHERE user_id=%s", (uid,))]
    keys = [
        r["file_uri"]
        for r in conn.execute("SELECT file_uri FROM agreements WHERE plan_id = ANY(%s)", (plans,))
    ]
    # calls cascade to facts and transcripts; agreements cascade to risks; plans to area scores
    conn.execute(
        "DELETE FROM calls WHERE batch_id IN (SELECT id FROM call_batches WHERE plan_id = ANY(%s))",
        (plans,),
    )
    conn.execute("DELETE FROM call_batches WHERE plan_id = ANY(%s)", (plans,))
    conn.execute("DELETE FROM agreements WHERE plan_id = ANY(%s)", (plans,))
    conn.execute("DELETE FROM move_plans WHERE user_id = %s", (uid,))
    conn.execute("DELETE FROM audit_events WHERE actor = %s", (str(uid),))
    delete_uploaded_files(keys)
    return {"plans": len(plans), "agreements": len(keys)}


def restore_sample_pgs(conn: psycopg.Connection) -> int:
    """Seed PGs that opted out during a rehearsal are made callable again."""
    conn.execute(
        "UPDATE pgs SET status = 'active' WHERE name ~ %s AND status <> 'active'",
        (SEED_PG_PATTERN,),
    )
    pgs = conn.execute("SELECT id FROM pgs WHERE name ~ %s", (SEED_PG_PATTERN,)).fetchall()
    restored = 0
    for pg in pgs:
        live = conn.execute(
            "SELECT 1 FROM consents WHERE subject_type='pg' AND subject_id=%s"
            " AND purpose='ai_call' AND revoked_at IS NULL",
            (pg["id"],),
        ).fetchone()
        if not live:
            conn.execute(
                "INSERT INTO consents (subject_type, subject_id, purpose, policy_version, channel)"
                " VALUES ('pg', %s, 'ai_call', %s, 'seed')",
                (pg["id"], CONSENT_POLICY),
            )
            restored += 1
    return restored


def add_sample_calls(conn: psycopg.Connection) -> int:
    from nguit_tools.extraction import extract_and_save
    from nguit_tools.extractors import RuleExtractor

    user = conn.execute(
        """
        INSERT INTO users (google_sub, email) VALUES (%s, %s)
        ON CONFLICT (google_sub) DO UPDATE SET deleted_at = NULL RETURNING id
        """,
        (DEMO_USER_SUB, DEMO_USER_EMAIL),
    ).fetchone()
    _, lat, lng = OFFICES["wipro circle"]
    plan = conn.execute(
        """
        INSERT INTO move_plans (user_id, office_address, office_location, budget_min, budget_max,
                                arrival_date, needs_json, status)
        VALUES (%s, 'Wipro Circle, Gachibowli, Hyderabad',
                ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, 8000, 14000,
                CURRENT_DATE + 14, '{"food": "any", "commute_mode": "any", "pg_gender": "any"}',
                'areas_ranked')
        RETURNING id
        """,
        (user["id"], lng, lat),
    ).fetchone()
    batch = conn.execute(
        "INSERT INTO call_batches (plan_id, approved_by, approved_at, status)"
        " VALUES (%s, %s, now(), 'approved') RETURNING id",
        (plan["id"], user["id"]),
    ).fetchone()
    made = 0
    for number, status, lines in SAMPLE_CALLS:
        pg = conn.execute(
            "SELECT id FROM pgs WHERE name = %s", (f"TEST PG {number:02d} (fake)",)
        ).fetchone()
        if pg is None:
            continue
        call = conn.execute(
            """
            INSERT INTO calls (batch_id, pg_id, plan_id, provider, language, status, started_at,
                               ended_at, end_reason)
            VALUES (%s, %s, %s, 'sample', 'en', %s, now(), now(), 'sample_recording')
            RETURNING id
            """,
            (batch["id"], pg["id"], plan["id"], status),
        ).fetchone()
        for i, (speaker, text) in enumerate(lines):
            conn.execute(
                "INSERT INTO transcript_segments (call_id, speaker, offset_ms, text)"
                " VALUES (%s, %s, %s, %s)",
                (call["id"], speaker, (i + 1) * 5000, text),
            )
        extract_and_save(conn, call["id"], RuleExtractor())  # same checks as a live call
        made += 1
    return made


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-calls", action="store_true", help="add 3 pre-recorded calls")
    args = parser.parse_args()
    refuse_unless_demo()

    url = os.environ["DATABASE_URL"]
    migrate(url)
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
        wiped = wipe_demo_user(conn)
        seed(conn)
        restored = restore_sample_pgs(conn)
        samples = add_sample_calls(conn) if args.sample_calls else 0
    print(f"Removed {wiped['plans']} demo plan(s) and {wiped['agreements']} uploaded file(s).")
    print(f"Restored sample areas and PGs ({restored} consent(s) given back).")
    if args.sample_calls:
        print(f"Added {samples} pre-recorded sample call(s) for the backup.")
    print("Demo is ready. Sign in with the demo account.")


if __name__ == "__main__":
    main()
