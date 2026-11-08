from datetime import UTC, datetime

import pytest
from google.api_core.exceptions import NotFound
from nguit_tools.storage import (
    AUDIO_KEY_PATTERN,
    GcsFileStore,
    LocalFileStore,
    get_audio_store,
    get_store,
)

KEY = "11111111-2222-3333-4444-555555555555.pdf"
AUDIO_KEY = "11111111-2222-3333-4444-555555555555.ogg"


class FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name, self.updated = bucket, name, datetime(2026, 1, 1, tzinfo=UTC)

    def upload_from_string(self, data, content_type=None):
        self.bucket.files[self.name] = data

    def download_as_bytes(self):
        if self.name not in self.bucket.files:
            raise NotFound("missing")
        return self.bucket.files[self.name]

    def delete(self):
        if self.name not in self.bucket.files:
            raise NotFound("missing")
        del self.bucket.files[self.name]


class FakeBucket:
    def __init__(self, name):
        self.name, self.files = name, {}

    def blob(self, name):
        return FakeBlob(self, name)


class FakeClient:
    """Just enough of google.cloud.storage.Client for the store."""

    def __init__(self):
        self.buckets = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket(name))

    def list_blobs(self, bucket):
        return [FakeBlob(bucket, n) for n in bucket.files]


@pytest.fixture(params=["local", "gcs"])
def store(request, tmp_path):
    """Both stores must behave the same way."""
    if request.param == "local":
        return LocalFileStore(str(tmp_path))
    return GcsFileStore("test-bucket", client=FakeClient())


def test_save_read_delete_round_trip(store):
    store.save(KEY, b"hello")
    assert store.read(KEY) == b"hello"
    store.delete(KEY)
    store.delete(KEY)  # deleting twice is fine
    assert store.list_objects() == []


def test_keys_that_could_escape_the_store_are_refused(store):
    for bad in ["../x.pdf", "a.pdf", "/abs.pdf", "x" * 36 + ".exe", f"dir/{KEY}"]:
        with pytest.raises(ValueError):
            store.save(bad, b"x")
        with pytest.raises(ValueError):
            store.read(bad)
        with pytest.raises(ValueError):
            store.delete(bad)


def test_listing_returns_keys_and_times_and_ignores_foreign_files(store):
    store.save(KEY, b"1")
    listed = store.list_objects()
    assert [k for k, _ in listed] == [KEY]
    assert listed[0][1].tzinfo is not None


def test_audio_store_uses_its_own_key_shape(tmp_path):
    audio = LocalFileStore(str(tmp_path), pattern=AUDIO_KEY_PATTERN)
    audio.save(AUDIO_KEY, b"ogg")
    assert audio.read(AUDIO_KEY) == b"ogg"
    with pytest.raises(ValueError):
        audio.save(KEY, b"pdf")  # an agreement key is not an audio key


def test_gcs_files_go_into_the_named_bucket_only():
    client = FakeClient()
    GcsFileStore("agreements-bucket", client=client).save(KEY, b"data")
    assert client.buckets["agreements-bucket"].files == {KEY: b"data"}
    assert "other" not in client.buckets


def test_the_bucket_is_chosen_by_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("DOCUMENT_BUCKET", raising=False)
    monkeypatch.setenv("AGREEMENT_STORAGE_DIR", str(tmp_path))
    assert isinstance(get_store(), LocalFileStore)
    monkeypatch.delenv("AUDIO_BUCKET", raising=False)
    assert get_audio_store() is None  # nothing is recorded until an audio bucket exists
