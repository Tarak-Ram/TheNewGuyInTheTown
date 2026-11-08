"""Checks that the Terraform and the application code agree, and that the safety promises hold.

`terraform validate` checks the shape of the files. It cannot know that a health-check path
exists, that an environment variable is spelled the way the code reads it, or that a bucket is
private. These tests read the .tf files as text and check those things against the real code.
"""

import re
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "infra" / "modules" / "platform"
STAGING = ROOT / "infra" / "envs" / "staging"


def tf(name: str) -> str:
    return (MODULE / name).read_text(encoding="utf-8")


def all_tf() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in ROOT.joinpath("infra").rglob("*.tf"))


def python_source() -> str:
    parts = []
    for folder in ("apps", "packages"):
        for p in (ROOT / folder).rglob("*.py"):
            if "tests" not in p.parts and ".venv" not in p.parts:
                parts.append(p.read_text(encoding="utf-8"))
    return "\n".join(parts)


def paths_of(app) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


# -- the paths Terraform calls really exist --------------------------------------------------------
def test_health_paths_used_by_probes_and_uptime_checks_exist():
    from relocation_api.main import app as api
    from relocation_worker.main import app as worker
    from voice_gateway.main import app as gateway

    for app in (api, worker, gateway):
        assert {"/health", "/health/ready"} <= paths_of(app)
    assert (ROOT / "apps/web/app/api/health/route.ts").exists()
    text = tf("run.tf") + tf("monitoring.tf")
    assert '"/health"' in text and '"/health/ready"' in text and '"/api/health"' in text


def test_the_scheduler_calls_a_real_worker_endpoint():
    from relocation_worker.main import app as worker

    uri = re.search(r'uri\s*=\s*"\$\{local\.service_url\.worker\}(/[^"]+)"', tf("run.tf"))
    assert uri and uri.group(1) in paths_of(worker)


def test_the_migration_job_runs_a_real_command():
    assert '["python", "-m", "relocation_api.migrate"]' in tf("run.tf")
    migrate = (ROOT / "apps/api/relocation_api/migrate.py").read_text(encoding="utf-8")
    assert "def main" in migrate and '__name__ == "__main__"' in migrate


def test_container_ports_match_what_the_images_listen_on():
    run = tf("run.tf")
    assert run.count("container_port = 8000") == 3  # api, gateway, worker
    assert run.count("container_port = 3000") == 1  # web
    python_image = (ROOT / "apps/Dockerfile.python").read_text(encoding="utf-8")
    assert "--port 8000" in python_image
    assert "PORT=3000" in (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")


# -- environment variables are spelled the way the code reads them -------------------------
EXTERNAL = {"GOOGLE_CLOUD_LOCATION"}  # read by Google's libraries, not by our own code


def test_every_environment_variable_in_terraform_is_read_by_the_code():
    run = tf("run.tf")
    block = run[run.index("common_env = {") : run.index("secret_env = {")]
    names = set(re.findall(r"^\s+([A-Z][A-Z_]+)\s+=", block, flags=re.M))
    secrets = set(re.findall(r"^\s+([A-Z][A-Z_]+)\s+=\s+\"[a-z-]+\"", run, flags=re.M))
    source = python_source()
    web_files = (ROOT / "apps/web/app").rglob("*.ts*")
    web = "\n".join(p.read_text(encoding="utf-8") for p in web_files)
    wanted = (names | secrets) - EXTERNAL
    missing = sorted(n for n in wanted if n not in source and n not in web)
    assert missing == [], f"set in Terraform but never read by the code: {missing}"


def test_the_web_app_gets_the_variables_it_reads():
    run = tf("run.tf")
    web_block = run[run.index('resource "google_cloud_run_v2_service" "web"') :]
    for name in ("API_URL", "GATEWAY_PUBLIC_URL", "GOOGLE_CLIENT_ID", "DEMO_MODE"):
        assert f'"{name}"' in web_block


# -- the safety promises ------------------------------------------------------------------------------------------
def test_real_phone_calls_are_off_and_not_a_setting():
    run = tf("run.tf")
    assert re.search(r'CALLING_ENABLED\s*=\s*"false"', run)
    assert "var.calling" not in all_tf()
    assert 'variable "calling' not in all_tf()


def test_demo_mode_is_off_in_staging():
    assert re.search(r"demo_mode\s*=\s*false", (STAGING / "main.tf").read_text(encoding="utf-8"))


def test_both_buckets_are_private_with_real_deletion():
    data = tf("data.tf")
    assert data.count('public_access_prevention    = "enforced"') == 2
    assert data.count("uniform_bucket_level_access = true") == 2
    assert data.count("retention_duration_seconds = 0") == 2  # no 7-day soft delete
    assert "allUsers" not in data and "allAuthenticatedUsers" not in data


def test_bucket_backstops_are_longer_than_the_retention_policy():
    from nguit_tools.retention import AUDIO_DAYS
    from relocation_api.agreements import RETENTION_DAYS

    data = tf("data.tf")
    ages = [int(x) for x in re.findall(r"age\s*=\s*(\d+)", data)]
    assert ages == [100, 32]
    assert ages[0] > RETENTION_DAYS == 90
    assert ages[1] > AUDIO_DAYS == 30


def test_the_worker_is_not_public_but_the_browser_facing_services_are():
    iam = tf("iam.tf")
    public = iam[iam.index('"public"') : iam.index('"worker_invokers"')]
    assert all(s in public for s in ("web", "api", "gateway"))
    assert "worker" not in public
    invokers = iam[iam.index('"worker_invokers"') :]
    assert '["scheduler", "tasks"]' in invokers and "allUsers" not in invokers


def test_the_database_is_not_open_to_the_internet():
    data = tf("data.tf")
    assert "authorized_networks" not in data
    assert 'ssl_mode     = "ENCRYPTED_ONLY"' in data
    assert "point_in_time_recovery_enabled = true" in data
    assert re.search(r"enabled\s+=\s+true", data)
    assert re.search(
        r'variable "db_deletion_protection"\s*{[^}]*default\s*=\s*true', tf("variables.tf"), re.S
    )


def test_no_service_account_has_broad_roles():
    text = all_tf()
    for broad in ("roles/owner", "roles/editor", "roles/run.admin", "roles/storage.admin"):
        assert broad not in text, broad


def test_the_deployer_can_only_be_used_from_the_main_branch_of_this_repo():
    delivery = tf("delivery.tf")
    assert 'assertion.ref == \\"refs/heads/main\\"' in delivery
    assert "assertion.repository ==" in delivery
    assert "private_key" not in all_tf() and "credentials" not in delivery


def test_no_secret_value_is_written_in_the_terraform_files():
    text = all_tf()
    assert not re.search(r"AIza[0-9A-Za-z_-]{20,}", text)  # a Google API key
    assert "-----BEGIN" not in text
    assert re.search(r'secret_data\s*=\s*"unset"', tf("data.tf"))  # only a placeholder


def test_the_voice_gateway_is_set_up_for_long_live_calls():
    gateway = tf("run.tf")
    gateway = gateway[gateway.index('"gateway" {') : gateway.index('"worker" {')]
    assert 'timeout                          = "3600s"' in gateway
    assert "session_affinity                 = true" in gateway
    assert "cpu_idle          = false" in gateway
    assert "var.gateway_min_instances" in gateway
    assert re.search(
        r'variable "gateway_min_instances"\s*{[^}]*default\s*=\s*1', tf("variables.tf"), re.S
    )


def test_services_wait_for_their_secrets_and_permissions():
    run = tf("run.tf")
    for resource in ('"api" {', '"gateway" {', '"worker" {'):
        block = run[run.index(resource) :]
        block = block[: block.index("\nresource ") if "\nresource " in block else len(block)]
        for needed in (
            "google_secret_manager_secret_version.generated",
            "google_secret_manager_secret_iam_member.access",
            "google_project_iam_member.sql_client",
        ):
            assert needed in block, f"{resource} does not wait for {needed}"


def test_the_retention_schedule_is_daily_in_india_time():
    run = tf("run.tf")
    assert 'schedule         = "30 3 * * *"' in run
    assert 'time_zone        = "Asia/Kolkata"' in run


# -- alerts and logs line up with what the code logs ----------------------------------------------------------------------
def test_log_based_metrics_match_events_the_code_really_logs():
    monitoring = tf("monitoring.tf")
    events = set(re.findall(r'jsonPayload\.event=\\"([a-z_]+)\\"', monitoring))
    logged = python_source()
    for event in events:
        assert f'"{event}"' in logged, f"alert watches for {event!r} but nothing logs it"
    for status in ("failed",):
        assert f'jsonPayload.status=\\"{status}\\"' in monitoring
    assert 'jsonPayload.reason=\\"disclosure_missing\\"' in monitoring
    assert '"disclosure_missing"' in logged


def test_every_alert_notifies_a_person():
    monitoring = tf("monitoring.tf")
    blocks = monitoring.count('resource "google_monitoring_alert_policy"')
    assert blocks == 5  # uptime (x3), errors, slow API, database, and the log alerts (x4)
    assert monitoring.count("notification_channels = local.channels") == blocks


def test_budget_alerts_cover_actual_and_forecast_spend():
    delivery = tf("delivery.tf")
    for pct in ("0.5", "0.9", "1.0"):
        assert f"threshold_percent = {pct}" in delivery
    assert "FORECASTED_SPEND" in delivery


# -- how the database address is built -----------------------------------------------------------------------------------
def test_the_database_url_format_is_one_the_app_can_connect_with():
    data = tf("data.tf")
    template = re.search(r'database_url\s*=\s*"([^"]+)"', data).group(1)
    assert "?host=/cloudsql/" in template and "@/" in template
    sample = "postgresql://app:pw@/relocation?host=/cloudsql/proj:asia-south1:db"
    parsed = psycopg.conninfo.conninfo_to_dict(sample)
    assert parsed["host"] == "/cloudsql/proj:asia-south1:db" and parsed["dbname"] == "relocation"


def test_terraform_state_and_variable_files_are_not_committable():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.tfstate", "terraform.tfvars", "backend.hcl", ".terraform/"):
        assert pattern in ignore
    assert (STAGING / "terraform.tfvars.example").exists()


@pytest.mark.parametrize(
    "name", ["versions.tf", "variables.tf", "main.tf", "data.tf", "iam.tf", "run.tf"]
)
def test_module_files_exist(name):
    assert (MODULE / name).exists()
