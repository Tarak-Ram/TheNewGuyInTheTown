import os
from collections.abc import Iterator

import psycopg
from psycopg.rows import dict_row


def get_conn() -> Iterator[psycopg.Connection]:
    """FastAPI dependency: one transaction per request, committed on success."""
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, row_factory=dict_row) as conn:
        yield conn
