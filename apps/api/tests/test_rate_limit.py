"""Rate limiting: a runaway client gets 429, normal use and other users are untouched."""

import pytest
from relocation_api import ratelimit
from relocation_api.ratelimit import Limiter, client_ip, pick_rule

from conftest import sign_in


# -- the counter itself (no database, no sleeping) -------------------------------------------
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_limiter_blocks_after_the_limit_and_frees_after_the_window():
    clock = Clock()
    limiter = Limiter(clock)
    rule = pick_rule("POST", "/v1/agreements/x/analyze")  # 5 per minute
    assert [limiter.check(rule, "u") for _ in range(5)] == [0] * 5
    wait = limiter.check(rule, "u")
    assert 1 <= wait <= rule.window + 1
    clock.now += rule.window
    assert limiter.check(rule, "u") == 0


def test_callers_are_counted_separately():
    limiter = Limiter(Clock())
    rule = pick_rule("DELETE", "/v1/me")
    for _ in range(rule.limit):
        assert limiter.check(rule, "a") == 0
    assert limiter.check(rule, "a") > 0
    assert limiter.check(rule, "b") == 0


def test_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_TRACKED", 100)
    limiter = Limiter(Clock())
    rule = pick_rule("GET", "/v1/plans")
    for i in range(1000):
        limiter.check(rule, f"caller-{i}")
    assert len(limiter._hits) <= 100


def test_rules_pick_the_expected_route():
    assert pick_rule("POST", "/v1/auth/google").name == "sign_in"
    assert pick_rule("POST", "/v1/plans/abc/rank-areas").name == "rank"
    assert pick_rule("PUT", "/v1/agreements/abc/file").name == "agreement_file"
    assert pick_rule("GET", "/v1/plans").name == "default"


def test_forwarded_for_uses_the_last_entry_a_caller_cannot_choose():
    scope = {"headers": [(b"x-forwarded-for", b"6.6.6.6, 7.7.7.7")], "client": ("1.1.1.1", 1)}
    assert client_ip(scope) == "7.7.7.7"
    assert client_ip({"headers": [], "client": ("1.1.1.1", 1)}) == "1.1.1.1"


# -- through the real app --------------------------------------------------------------------
def test_sign_in_is_limited_per_address(client):
    codes = [
        client.post("/v1/auth/google", json={"id_token": f"google-user{i}"}).status_code
        for i in range(25)
    ]
    assert codes[:20] == [200] * 20
    assert set(codes[20:]) == {429}


def test_the_429_tells_the_caller_when_to_retry(client):
    for i in range(20):
        client.post("/v1/auth/google", json={"id_token": f"google-u{i}"})
    res = client.post("/v1/auth/google", json={"id_token": "google-late"})
    assert res.status_code == 429
    assert int(res.headers["retry-after"]) >= 1
    assert "Too many requests" in res.json()["detail"]


def test_one_user_hitting_the_limit_does_not_block_another(client):
    a = sign_in(client, "ratea")
    b = sign_in(client, "rateb")
    for _ in range(3):
        client.delete("/v1/me", headers=a)  # first one deletes the account; the rest are 401/429
    # "a" is now limited on account deletion, but "b" is untouched by it
    res = client.get("/v1/me", headers=b)
    assert res.status_code == 200


def test_a_forged_token_cannot_dodge_the_limit_by_changing_its_id(client):
    codes = [
        client.post("/v1/auth/demo", headers={"Authorization": f"Bearer fake-{i}"}).status_code
        for i in range(25)
    ]
    # /auth/demo is 404 outside demo mode; either way the 21st call must be limited
    assert 429 in codes[20:]


def test_health_checks_are_never_limited(client):
    for _ in range(400):
        assert client.get("/health").status_code == 200


def test_normal_use_is_not_limited(client):
    headers = sign_in(client, "normaluser")
    for _ in range(50):
        assert client.get("/v1/me", headers=headers).status_code == 200


def test_it_can_be_switched_off(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    codes = {
        client.post("/v1/auth/google", json={"id_token": f"google-off{i}"}).status_code
        for i in range(30)
    }
    assert codes == {200}


@pytest.mark.parametrize("path", ["/v1/plans", "/v1/me"])
def test_the_backstop_limit_eventually_applies(client, path):
    headers = sign_in(client, "chatty" + path.replace("/", ""))
    codes = [client.get(path, headers=headers).status_code for _ in range(305)]
    assert 429 in codes[300:]
