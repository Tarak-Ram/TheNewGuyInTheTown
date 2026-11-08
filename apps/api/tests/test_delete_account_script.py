import importlib.util
import os
from pathlib import Path

import pytest
from nguit_tools.storage import LocalFileStore, get_audio_store

from conftest import sign_in

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def script():
    """Loads scripts/delete_account.py without letting its .env loading leak into the tests."""
    before = dict(os.environ)
    spec = importlib.util.spec_from_file_location(
        "delete_account", ROOT / "scripts" / "delete_account.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.environ.clear()
    os.environ.update(before)
    return module


@pytest.fixture
def env(client, tmp_path, monkeypatch, script):
    # The script reads DATABASE_URL from the environment; `client` already set it for the test DB.
    monkeypatch.setenv("AGREEMENT_STORAGE_DIR", str(tmp_path))
    monkeypatch.delenv("DOCUMENT_BUCKET", raising=False)
    monkeypatch.delenv("AUDIO_BUCKET", raising=False)
    monkeypatch.setattr(script, "load_dotenv", lambda path: None)  # never read the real .env
    assert get_audio_store() is None and LocalFileStore().base == tmp_path


def run(script, *args):
    return script.main(list(args))


def test_it_refuses_without_the_confirmation_word(script, env, capsys):
    assert run(script, "--email", "x@example.com") == 2
    assert run(script, "--email", "x@example.com", "--confirm", "yes") == 2
    assert "Refusing" in capsys.readouterr().out


def test_it_deletes_a_user_found_by_email_with_the_same_logic_as_the_app(
    script, env, client, conn, make_call, capsys
):
    c = make_call()
    email = client.get("/v1/me", headers=c.headers).json()["email"]

    assert run(script, "--email", email.upper(), "--confirm", "DELETE") == 0  # case-insensitive

    assert "Deleted: 1 plan(s), 1 call(s)" in capsys.readouterr().out
    assert conn.execute("SELECT 1 FROM move_plans WHERE id = %s", (c.plan_id,)).fetchone() is None
    assert client.get("/v1/me", headers=c.headers).status_code == 401
    audit = conn.execute("SELECT 1 FROM audit_events WHERE action = 'account_deleted'").fetchone()
    assert audit is not None


def test_it_can_find_a_user_by_id(script, env, client, conn, capsys):
    headers = sign_in(client, "script-by-id-user")
    uid = client.get("/v1/me", headers=headers).json()["id"]
    assert run(script, "--user-id", uid, "--confirm", "DELETE") == 0


def test_an_unknown_user_deletes_nothing(script, env, capsys):
    assert run(script, "--email", "nobody-at-all@example.com", "--confirm", "DELETE") == 1
    assert "No such user" in capsys.readouterr().out


def test_deleting_twice_is_harmless(script, env, client, capsys):
    headers = sign_in(client, "script-twice-user")
    uid = client.get("/v1/me", headers=headers).json()["id"]

    assert run(script, "--user-id", uid, "--confirm", "DELETE") == 0
    assert "Deleted:" in capsys.readouterr().out

    # The second run finds an account that is already deleted and changes nothing.
    assert run(script, "--user-id", uid, "--confirm", "DELETE") == 0
    assert "already deleted" in capsys.readouterr().out
