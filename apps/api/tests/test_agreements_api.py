from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from agreement_pdf import make_pdf, tiny_png
from nguit_schemas.agreements import DISCLAIMER
from nguit_tools.agreement_ai import TranscriptionFailed
from nguit_tools.agreement_check import AnalysisOutput, ModelRisk, PageText
from relocation_api.agreements import analyzer_dep, transcriber_dep
from relocation_api.main import app
from relocation_api.storage import LocalFileStore, get_store

from conftest import PLAN, sign_in

PDF = "application/pdf"
PNG = "image/png"
EVALS = Path(__file__).resolve().parents[3] / "evals" / "agreements"
LOCK_IN_TEXT = (
    "1. Rent. The Tenant shall pay Rs 9,500 per month.\n"
    "2. Lock-in. The Tenant is bound by a lock-in period of 11 months and shall not vacate "
    "the room before the end of this period.\n"
    "3. Notice. Either party may end this agreement with 30 days written notice.\n"
    "4. Deposit. The Owner holds a refundable security deposit of one month rent, returned "
    "within 15 days of the Tenant vacating the room after a joint inspection.\n"
    "5. Conduct. The Tenant shall keep the room clean and shall respect the other residents."
)


class FakeAnalyzer:
    name = "fake"

    def __init__(self, risks=(), language="en"):
        self.risks, self.language, self.calls = list(risks), language, 0

    def analyze(self, pages):
        self.calls += 1
        return AnalysisOutput(language=self.language, risks=self.risks)


class FakeTranscriber:
    def __init__(self, text=None, language="en", fail=False):
        self.pages = [PageText(1, text)] if text else []
        self.language, self.fail, self.calls = language, fail, 0

    def transcribe(self, data, content_type):
        self.calls += 1
        if self.fail:
            raise TranscriptionFailed("down")
        return self.pages, self.language


@pytest.fixture
def env(client, tmp_path):
    store = LocalFileStore(str(tmp_path))
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[analyzer_dep] = lambda: None
    app.dependency_overrides[transcriber_dep] = lambda: None
    return store


def use(analyzer=None, transcriber=None):
    app.dependency_overrides[analyzer_dep] = lambda: analyzer
    app.dependency_overrides[transcriber_dep] = lambda: transcriber


def mover(client, name):
    headers = sign_in(client, name)
    plan_id = client.post("/v1/plans", json=PLAN, headers=headers).json()["id"]
    return headers, plan_id


def create(client, headers, plan_id, *, filename="agreement.pdf", ctype=PDF, size=1000):
    res = client.post(
        "/v1/agreements",
        json={"plan_id": plan_id, "filename": filename, "content_type": ctype, "size_bytes": size},
        headers=headers,
    )
    return res


def upload(client, created, data):
    return client.put(created["upload_url"], content=data)


def check(client, headers, plan_id, data, ctype=PDF):
    """create -> upload -> analyze -> report, returning the report."""
    created = create(client, headers, plan_id, ctype=ctype, size=len(data)).json()
    assert upload(client, created, data).status_code == 200
    assert (
        client.post(f"/v1/agreements/{created['id']}/analyze", headers=headers).status_code == 202
    )
    return client.get(f"/v1/agreements/{created['id']}/report", headers=headers).json()


def pdf_of(text=LOCK_IN_TEXT, copies=1):
    return make_pdf(text, copies)


# -- the whole flow --------------------------------------------------------------------------
def test_pdf_upload_to_report(client, env):
    h, plan_id = mover(client, "agr-flow-user")
    report = check(client, h, plan_id, pdf_of())
    assert report["status"] == "done"
    assert report["text_source"] == "pdf_text_layer" and report["pages"] == 1
    lock_in = next(r for r in report["risks"] if r["type"] == "lock_in")
    assert "lock-in period of 11 months" in lock_in["quote"]
    assert lock_in["page"] == 1 and lock_in["severity"] == "high"
    assert lock_in["explanation"] and lock_in["question_to_ask"]
    assert report["risk_counts"]["high"] >= 1


def test_the_stored_file_is_private_and_hashed(client, env, conn):
    h, plan_id = mover(client, "agr-private-user")
    data = pdf_of()
    created = create(client, h, plan_id, size=len(data)).json()
    upload(client, created, data)
    row = conn.execute(
        "SELECT file_uri, sha256, delete_after FROM agreements WHERE id=%s", (created["id"],)
    ).fetchone()
    import hashlib

    assert row["sha256"] == hashlib.sha256(data).hexdigest()
    assert env.read(row["file_uri"]) == data
    assert row["delete_after"] > datetime.now(UTC) + timedelta(days=89)  # 90-day retention
    assert client.get(f"/{row['file_uri']}").status_code == 404  # not served by anything


def test_the_sample_pdfs_are_checked_through_the_real_text_layer(client, env):
    h, plan_id = mover(client, "agr-samples-user")
    text = (EVALS / "g_multi.txt").read_text(encoding="utf-8")
    report = check(client, h, plan_id, make_pdf(text))
    found = {r["type"] for r in report["risks"]}
    assert {
        "lock_in",
        "early_exit_penalty",
        "deposit_deduction",
        "owner_entry",
        "eviction_terms",
    } <= found
    assert all(r["quote"] and r["page"] == 1 for r in report["risks"])


def test_reanalysis_replaces_the_risks_instead_of_duplicating_them(client, env):
    h, plan_id = mover(client, "agr-again-user")
    data = pdf_of()
    created = create(client, h, plan_id, size=len(data)).json()
    upload(client, created, data)
    for _ in range(2):
        client.post(f"/v1/agreements/{created['id']}/analyze", headers=h)
    risks = client.get(f"/v1/agreements/{created['id']}/report", headers=h).json()["risks"]
    assert len([r for r in risks if r["type"] == "lock_in"]) == 1


# -- D-4: the notice is on every result --------------------------------------------------------
def test_not_legal_advice_notice_is_on_every_status(client, env):
    h, plan_id = mover(client, "agr-notice-user")
    data = pdf_of()
    created = create(client, h, plan_id, size=len(data)).json()
    seen = {}

    def snap():
        r = client.get(f"/v1/agreements/{created['id']}/report", headers=h).json()
        seen[r["status"]] = r["disclaimer"]

    snap()  # awaiting_upload
    upload(client, created, data)
    snap()  # uploaded
    client.post(f"/v1/agreements/{created['id']}/analyze", headers=h)
    snap()  # done
    # unreadable photo
    use(transcriber=FakeTranscriber(text=None))
    unreadable = check(client, h, plan_id, tiny_png(), PNG)
    seen[unreadable["status"]] = unreadable["disclaimer"]
    # failed (photo, and no reader available)
    use()
    failed = check(client, h, plan_id, tiny_png(), PNG)
    seen[failed["status"]] = failed["disclaimer"]

    assert {"awaiting_upload", "uploaded", "done", "unreadable", "failed"} <= set(seen)
    assert all(text == DISCLAIMER for text in seen.values())
    assert "not legal advice" in DISCLAIMER.lower()


# -- D-1: what can be uploaded -----------------------------------------------------------------
@pytest.mark.parametrize("ctype", ["text/plain", "image/gif", "application/zip", "text/html"])
def test_other_file_types_are_refused_up_front(client, env, ctype):
    h, plan_id = mover(client, "agr-type-user")
    assert create(client, h, plan_id, ctype=ctype).status_code == 415


def test_oversize_files_are_refused_up_front(client, env):
    h, plan_id = mover(client, "agr-size-user")
    assert create(client, h, plan_id, size=16 * 1024 * 1024).status_code == 413


def test_a_disguised_file_is_rejected_at_upload_and_never_stored(client, env, tmp_path):
    h, plan_id = mover(client, "agr-fake-user")
    exe = b"MZ\x90\x00" + b"0" * 100
    created = create(client, h, plan_id, size=len(exe)).json()
    res = upload(client, created, exe)
    assert res.status_code == 422 and "PDF, JPEG and PNG" in res.json()["detail"]
    assert list(tmp_path.iterdir()) == []
    report = client.get(f"/v1/agreements/{created['id']}/report", headers=h).json()
    assert report["status"] == "failed" and report["disclaimer"] == DISCLAIMER


def test_more_than_twenty_pages_is_rejected(client, env):
    h, plan_id = mover(client, "agr-pages-user")
    data = pdf_of(copies=21)
    created = create(client, h, plan_id, size=len(data)).json()
    res = upload(client, created, data)
    assert res.status_code == 422 and "20" in res.json()["detail"]


def test_twenty_pages_is_accepted(client, env):
    h, plan_id = mover(client, "agr-20pages-user")
    data = pdf_of(copies=20)
    created = create(client, h, plan_id, size=len(data)).json()
    assert upload(client, created, data).status_code == 200


def test_a_file_bigger_than_the_limit_is_stopped_while_uploading(client, env):
    h, plan_id = mover(client, "agr-huge-user")
    created = create(client, h, plan_id, size=1000).json()  # claims to be small
    res = upload(client, created, b"%PDF-" + b"0" * (16 * 1024 * 1024))
    assert res.status_code == 413


# -- upload links ---------------------------------------------------------------------------------
def test_an_upload_link_works_only_once(client, env):
    h, plan_id = mover(client, "agr-once-user")
    data = pdf_of()
    created = create(client, h, plan_id, size=len(data)).json()
    assert upload(client, created, data).status_code == 200
    assert upload(client, created, data).status_code == 409


def test_a_wrong_or_missing_token_is_refused(client, env):
    h, plan_id = mover(client, "agr-token-user")
    created = create(client, h, plan_id).json()
    assert client.put(f"/v1/agreements/{created['id']}/file", content=pdf_of()).status_code == 401
    bad = f"/v1/agreements/{created['id']}/file?token=nonsense"
    assert client.put(bad, content=pdf_of()).status_code == 401


def test_a_link_for_one_agreement_cannot_upload_to_another(client, env):
    h, plan_id = mover(client, "agr-swap-user")
    first = create(client, h, plan_id).json()
    second = create(client, h, plan_id).json()
    token = first["upload_url"].split("token=")[1]
    res = client.put(f"/v1/agreements/{second['id']}/file?token={token}", content=pdf_of())
    assert res.status_code == 401


def test_an_expired_link_is_refused(client, env):
    h, plan_id = mover(client, "agr-expired-user")
    created = create(client, h, plan_id).json()
    claims = {"sub": created["id"], "jti": "x", "aud": "agreement-upload",
              "exp": datetime.now(UTC) - timedelta(minutes=1)}  # fmt: skip
    token = jwt.encode(claims, "test-secret-test-secret-test-secret", algorithm="HS256")
    res = client.put(f"/v1/agreements/{created['id']}/file?token={token}", content=pdf_of())
    assert res.status_code == 401


def test_the_link_is_short_lived(client, env):
    h, plan_id = mover(client, "agr-ttl-user")
    created = create(client, h, plan_id).json()
    assert created["expires_in"] <= 300 and created["max_bytes"] == 15 * 1024 * 1024


# -- access control -----------------------------------------------------------------------------
def test_other_users_cannot_see_analyse_or_upload_to_an_agreement(client, env):
    h, plan_id = mover(client, "agr-owner-user")
    stranger = sign_in(client, "agr-stranger-user")
    data = pdf_of()
    created = create(client, h, plan_id, size=len(data)).json()
    upload(client, created, data)
    assert client.get(f"/v1/agreements/{created['id']}/report", headers=stranger).status_code == 404
    assert (
        client.post(f"/v1/agreements/{created['id']}/analyze", headers=stranger).status_code == 404
    )
    assert create(client, stranger, plan_id).status_code == 404  # not their plan


def test_everything_needs_sign_in(client, env):
    assert client.post("/v1/agreements", json={}).status_code == 401
    assert (
        client.get("/v1/agreements/00000000-0000-0000-0000-000000000000/report").status_code == 401
    )


def test_analysing_before_uploading_is_refused(client, env):
    h, plan_id = mover(client, "agr-early-user")
    created = create(client, h, plan_id).json()
    assert client.post(f"/v1/agreements/{created['id']}/analyze", headers=h).status_code == 409


# -- photos, scans and unreadable images -----------------------------------------------------------
def test_a_readable_photo_is_checked_and_marked_as_read_from_a_photo(client, env):
    h, plan_id = mover(client, "agr-photo-user")
    use(transcriber=FakeTranscriber(LOCK_IN_TEXT))
    report = check(client, h, plan_id, tiny_png(), PNG)
    assert report["status"] == "done" and report["text_source"] == "model_transcription"
    assert any(r["type"] == "lock_in" for r in report["risks"])
    assert any("photo or scan" in w for w in report["warnings"])


def test_an_unreadable_photo_analyses_nothing_and_asks_for_a_clearer_one(client, env):
    h, plan_id = mover(client, "agr-blurry-user")
    analyzer = FakeAnalyzer([])
    use(analyzer=analyzer, transcriber=FakeTranscriber(text=None))
    report = check(client, h, plan_id, tiny_png(), PNG)
    assert report["status"] == "unreadable" and report["risks"] == []
    assert "clearer photo" in report["message"]
    assert analyzer.calls == 0  # nothing was analysed from an image we could not read


def test_a_transcription_that_is_mostly_noise_counts_as_unreadable(client, env):
    h, plan_id = mover(client, "agr-noise-user")
    use(transcriber=FakeTranscriber("%#@ !! ~~ ^^ " * 30))
    assert check(client, h, plan_id, tiny_png(), PNG)["status"] == "unreadable"


def test_a_photo_without_an_available_reader_fails_with_a_clear_message(client, env):
    h, plan_id = mover(client, "agr-noreader-user")
    report = check(client, h, plan_id, tiny_png(), PNG)
    assert report["status"] == "failed" and "AI reader" in report["message"]


def test_a_failing_reader_gives_a_clear_failure_not_a_hang(client, env):
    h, plan_id = mover(client, "agr-readerdown-user")
    use(transcriber=FakeTranscriber(fail=True))
    assert check(client, h, plan_id, tiny_png(), PNG)["status"] == "failed"


def test_a_scanned_pdf_with_no_text_layer_goes_through_the_reader(client, env):
    h, plan_id = mover(client, "agr-scan-user")
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)  # one page, no text layer, like a scan
    out = io.BytesIO()
    writer.write(out)
    blank = out.getvalue()
    transcriber = FakeTranscriber(LOCK_IN_TEXT)
    use(transcriber=transcriber)
    report = check(client, h, plan_id, blank)
    assert transcriber.calls == 1 and report["text_source"] == "model_transcription"
    assert report["status"] == "done"


# -- D-3 and prompt injection, through the API ---------------------------------------------------
def test_a_made_up_model_quote_never_reaches_the_user(client, env, conn):
    h, plan_id = mover(client, "agr-fabric-user")
    fabricated = ModelRisk(
        type="lock_in", severity="high", quote="The Tenant must pay a Rs 99,000 joining fee.",
        explanation="Hidden fee.", question_to_ask="Why?",
    )  # fmt: skip
    use(analyzer=FakeAnalyzer([fabricated]))
    report = check(client, h, plan_id, pdf_of())
    assert all("99,000" not in r["quote"] for r in report["risks"])
    n = conn.execute("SELECT discarded_risks FROM agreements ORDER BY created_at DESC LIMIT 1")
    assert n.fetchone()["discarded_risks"] == 1


def test_an_injected_instruction_cannot_hide_the_real_risks(client, env):
    h, plan_id = mover(client, "agr-inject-user")
    text = (EVALS / "e_injection.txt").read_text(encoding="utf-8")
    use(analyzer=FakeAnalyzer([]))  # a model that obeyed the document: "no risks"
    report = check(client, h, plan_id, make_pdf(text))
    assert report["injection_detected"] is True
    assert any(r["type"] == "lock_in" for r in report["risks"])
    assert any("instructions to an AI" in w for w in report["warnings"])
    assert report["disclaimer"] == DISCLAIMER


def test_a_clean_agreement_shows_no_risks_but_still_the_notice(client, env):
    h, plan_id = mover(client, "agr-clean-user")
    text = (EVALS / "f_clean.txt").read_text(encoding="utf-8")
    report = check(client, h, plan_id, make_pdf(text))
    assert report["status"] == "done" and report["risks"] == []
    assert report["disclaimer"] == DISCLAIMER


def test_a_non_english_clause_shows_the_original_beside_the_translation(client, env):
    h, plan_id = mover(client, "agr-hindi-user")
    hindi = "किरायेदार 11 महीने तक कमरा खाली नहीं कर सकता। " * 8
    risk = ModelRisk(
        type="lock_in", severity="high", quote="किरायेदार 11 महीने तक कमरा खाली नहीं कर सकता",
        quote_translation="The tenant cannot vacate the room for 11 months.",
        explanation="You must stay for 11 months.", question_to_ask="Can the lock-in be shorter?",
    )  # fmt: skip
    use(
        analyzer=FakeAnalyzer([risk], language="Hindi"), transcriber=FakeTranscriber(hindi, "Hindi")
    )
    report = check(client, h, plan_id, tiny_png(), PNG)
    assert report["language"] == "Hindi"
    assert report["risks"][0]["quote"].startswith("किरायेदार")
    assert report["risks"][0]["quote_translation"].startswith("The tenant cannot vacate")


# -- failures do not leave things stuck -----------------------------------------------
def test_a_crash_during_analysis_ends_as_failed_not_stuck_analysing(client, env):
    h, plan_id = mover(client, "agr-crash-user")
    data = pdf_of()
    created = create(client, h, plan_id, size=len(data)).json()
    upload(client, created, data)
    for f in Path(env.base).iterdir():
        f.unlink()  # the stored file disappears
    client.post(f"/v1/agreements/{created['id']}/analyze", headers=h)
    report = client.get(f"/v1/agreements/{created['id']}/report", headers=h).json()
    assert report["status"] == "failed" and report["disclaimer"] == DISCLAIMER


def test_audit_events_are_written(client, env, conn):
    h, plan_id = mover(client, "agr-audit-user")
    report = check(client, h, plan_id, pdf_of())
    actions = {
        r["action"]
        for r in conn.execute(
            "SELECT action FROM audit_events WHERE object_id = %s", (report["id"],)
        ).fetchall()
    }
    assert {"agreement_created", "agreement_analyzed"} <= actions


# -- storage ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "key", ["../etc/passwd", "..\\x.pdf", "a.pdf", "/abs/path.pdf", "x" * 36 + ".exe"]
)
def test_storage_refuses_keys_that_could_escape_the_folder(tmp_path, key):
    with pytest.raises(ValueError):
        LocalFileStore(str(tmp_path)).read(key)


def test_storage_round_trip_and_delete(tmp_path):
    store = LocalFileStore(str(tmp_path))
    key = "11111111-2222-3333-4444-555555555555.pdf"
    store.save(key, b"hello")
    assert store.read(key) == b"hello"
    store.delete(key)
    store.delete(key)  # deleting twice is fine
    assert not (tmp_path / key).exists()
