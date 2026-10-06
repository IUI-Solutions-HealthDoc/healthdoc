"""Configure which facilities the test bridge serves (integrations/abdm/facilities.py)."""

from types import SimpleNamespace

from app.integrations.abdm import facilities


def serve(monkeypatch, hfr: str, *, hip: str | None = None, hiu: str | None = None, more: str = "") -> None:
    """The first facility is `hfr`, speaking as `hip`/`hiu` (default: `hfr`);
    `more` lists additional facilities' HFR ids, comma-separated."""
    monkeypatch.setattr(
        facilities,
        "get_settings",
        lambda: SimpleNamespace(
            abdm_hfr_facility_id=hfr,
            abdm_hip_id=hip or hfr,
            abdm_hiu_id=hiu or hfr,
            abdm_additional_hfr_facility_ids=more,
        ),
    )
