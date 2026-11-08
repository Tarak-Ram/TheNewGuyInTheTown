import os

import psycopg
from nguit_tools.health import create_app
from nguit_tools.retention import run_retention
from nguit_tools.storage import get_audio_store, get_store
from psycopg.rows import dict_row

app = create_app("worker", "Relocation Worker")


@app.post("/internal/retention/run")
def retention() -> dict[str, int]:
    """Deletes agreements after 90 days and audio after 30. Idempotent.

    In staging and production this service accepts only authenticated calls from Cloud
    Scheduler (Cloud Run IAM), so it is not reachable from the internet.
    """
    with psycopg.connect(
        os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5
    ) as conn:
        return run_retention(conn, get_store(), get_audio_store()).as_dict()
