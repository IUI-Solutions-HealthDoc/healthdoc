"""Origin evidence must survive container replacement without logging secrets."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_forwarded_claims_and_receipt_ids_are_recorded_without_bodies_or_queries():
    config = (ROOT / "infra/nginx/nginx.conf").read_text()
    log_format = config.split("log_format main", 1)[1].split(";", 1)[0]
    for field in ("$healthdoc_cf_ip_claim", "$healthdoc_xff_claim", "$sent_http_x_healthdoc_receipt_id"):
        assert field in log_format
    assert "map $http_cf_connecting_ip $healthdoc_cf_ip_claim" in config
    assert "map $http_x_forwarded_for $healthdoc_xff_claim" in config
    for forbidden in ("$request_body", "$http_authorization", "$args", "$http_referer", '"$request"'):
        assert forbidden not in log_format
    assert "access_log /var/log/healthdoc/access-$healthdoc_log_day.log main;" in config
    assert "access_log /var/log/nginx/access.log main;" in config
    assert "root /usr/share/nginx/html;" in config


def test_both_deployments_mount_a_named_log_volume_and_enable_callback_receipts():
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = yaml.safe_load((ROOT / "infra" / filename).read_text())
        assert "nginx-logs" in compose["volumes"]
        mounts = compose["services"]["nginx"]["volumes"]
        assert "nginx-logs:/var/log/healthdoc" in mounts
        assert any("/docker-entrypoint.d/10-persistent-logs.sh:ro" in mount for mount in mounts)
        assert "ABDM_CALLBACK_EVIDENCE_ENABLED" in compose["services"]["backend"]["environment"]


def test_retention_is_restricted_to_our_dated_files_in_the_private_volume():
    hook = ROOT / "infra/nginx/10-persistent-logs.sh"
    source = hook.read_text()
    assert hook.stat().st_mode & 0o111
    assert "chmod 0700 /var/log/healthdoc" in source
    assert "-maxdepth 1 -type f -name 'access-????-??-??.log' -mtime +6 -delete" in source
    assert "rm -rf" not in source
