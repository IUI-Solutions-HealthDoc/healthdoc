"""Static contracts for the production Prometheus/Grafana bundle."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
OBSERVABILITY = ROOT / "infra" / "observability"


def test_prometheus_scrapes_only_the_internal_backend_and_loads_rules() -> None:
    config = yaml.safe_load((OBSERVABILITY / "prometheus.yml").read_text())
    [scrape] = config["scrape_configs"]
    assert scrape["job_name"] == "healthdoc-backend"
    assert scrape["metrics_path"] == "/metrics"
    assert scrape["static_configs"] == [{"targets": ["backend:8000"]}]
    assert config["rule_files"] == ["/etc/prometheus/alerts.yml"]


def test_alerts_cover_availability_errors_and_latency_without_clinical_guesses() -> None:
    config = yaml.safe_load((OBSERVABILITY / "alerts.yml").read_text())
    names = {rule["alert"] for group in config["groups"] for rule in group["rules"]}
    assert names == {
        "HealthDocBackendDown",
        "HealthDocHighErrorRate",
        "HealthDocHighP95Latency",
        "HealthDocCallbackEvidenceStorageFailed",
    }
    receipt_rule = next(rule for group in config["groups"] for rule in group["rules"]
                        if rule["alert"] == "HealthDocCallbackEvidenceStorageFailed")
    assert receipt_rule["expr"] == "sum(increase(abdm_callback_evidence_failures_total[5m])) > 0"


def test_grafana_dashboard_uses_the_provisioned_prometheus_source() -> None:
    dashboard = json.loads(
        (OBSERVABILITY / "grafana" / "dashboards" / "healthdoc-api.json").read_text()
    )
    assert dashboard["uid"] == "healthdoc-api"
    assert {panel["id"] for panel in dashboard["panels"]} == {1, 2, 3, 4}
    assert all(
        panel["datasource"]["uid"] == "healthdoc-prometheus"
        for panel in dashboard["panels"]
    )


def test_grafana_disables_background_downloads_and_update_checks() -> None:
    compose = yaml.safe_load((ROOT / "infra" / "docker-compose.prod.yml").read_text())
    environment = compose["services"]["grafana"]["environment"]
    assert environment["GF_ANALYTICS_CHECK_FOR_UPDATES"] == "false"
    assert environment["GF_ANALYTICS_CHECK_FOR_PLUGIN_UPDATES"] == "false"
    assert environment["GF_PLUGINS_PLUGIN_ADMIN_ENABLED"] == "false"
    assert environment["GF_PLUGINS_PREINSTALL_DISABLED"] == "true"
    assert environment["GF_PLUGINS_PREINSTALL_AUTO_UPDATE"] == "false"
