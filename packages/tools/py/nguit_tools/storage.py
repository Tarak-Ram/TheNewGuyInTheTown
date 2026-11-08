"""Private file storage for agreements (and, later, call audio).

Two interchangeable stores with the same methods:
  - LocalFileStore: a folder on disk, for local development and tests.
  - GcsFileStore: a private Cloud Storage bucket, for staging and production.
`get_store()` picks the bucket when DOCUMENT_BUCKET is set, and the local folder otherwise.

Files are never served directly. They are read only by the API, after the owner check.
A key must look like "<uuid>.<ext>", so nothing built from user input can name another path.
"""

import os
import re
from datetime import UTC, datetime
from pathlib import Path

KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(pdf|jpg|png)$"
)
AUDIO_KEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(ogg|wav|mp3|webm)$"
)
EXTENSIONS = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}


def key_for(agreement_id, content_type: str) -> str:
    return f"{agreement_id}.{EXTENSIONS[content_type]}"


def _check(key: str, pattern: re.Pattern) -> str:
    if not pattern.match(key):
        raise ValueError("invalid storage key")
    return key


class LocalFileStore:
    def __init__(self, base_dir: str | None = None, pattern: re.Pattern = KEY_PATTERN):
        self.base = Path(base_dir or os.environ.get("AGREEMENT_STORAGE_DIR", "./data/agreements"))
        self.pattern = pattern

    def _path(self, key: str) -> Path:
        return self.base / _check(key, self.pattern)

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)  # no half-written files

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def list_objects(self) -> list[tuple[str, datetime]]:
        """(key, last modified) for every stored file. Used to find orphans."""
        if not self.base.exists():
            return []
        return [
            (p.name, datetime.fromtimestamp(p.stat().st_mtime, UTC))
            for p in self.base.iterdir()
            if self.pattern.match(p.name)
        ]


class GcsFileStore:
    """A private Cloud Storage bucket. The bucket itself enforces no public access."""

    def __init__(self, bucket_name: str, client=None, pattern: re.Pattern = KEY_PATTERN):
        if client is None:
            from google.cloud import storage  # imported here so local runs do not need it

            client = storage.Client()
        self.client = client
        self.bucket = client.bucket(bucket_name)
        self.pattern = pattern

    def save(self, key: str, data: bytes) -> None:
        self.bucket.blob(_check(key, self.pattern)).upload_from_string(
            data, content_type="application/octet-stream"
        )

    def read(self, key: str) -> bytes:
        return self.bucket.blob(_check(key, self.pattern)).download_as_bytes()

    def delete(self, key: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(_check(key, self.pattern)).delete()
        except NotFound:
            pass  # already gone: deleting twice is fine

    def list_objects(self) -> list[tuple[str, datetime]]:
        return [
            (b.name, b.updated or datetime.now(UTC))
            for b in self.client.list_blobs(self.bucket)
            if self.pattern.match(b.name)
        ]


def get_store() -> LocalFileStore | GcsFileStore:
    bucket = os.environ.get("DOCUMENT_BUCKET")
    return GcsFileStore(bucket) if bucket else LocalFileStore()


def get_audio_store() -> LocalFileStore | GcsFileStore | None:
    """Call recordings. None when no audio bucket is configured (nothing is recorded yet)."""
    bucket = os.environ.get("AUDIO_BUCKET")
    return GcsFileStore(bucket, pattern=AUDIO_KEY_PATTERN) if bucket else None
