import json
from pathlib import Path

from agile_forecast.regions import convert, forecasts


def test_all_regions_match_octopus_across_vat_transition():
    # Public AGILE-24-10-01 API samples retrieved 1 October 2026. Include
    # peak/off-peak periods on both sides of the change, using the same
    # tolerance as the production feed safeguard (API rounds to 0.01p).
    samples = json.loads(
        (Path(__file__).parent / "fixtures/octopus_vat_transition.json").read_text()
    )
    assert len({sample["region"] for sample in samples}) == 14
    for sample in samples:
        assert abs(
            convert(sample["north_west"], sample["start"], sample["region"])
            - sample["regional"]
        ) <= 0.025


def test_current_regional_prices_include_all_day_reduction_and_vat():
    assert convert(10, "2026-09-19T10:00:00Z", "E") == 10
    assert convert(10, "2026-09-19T10:00:00Z", "B") == 9.357
    assert convert(30, "2026-09-19T15:00:00Z", "A") == 31.05
    assert convert(30, "2026-09-19T18:00:00Z", "A") == 30
    assert convert(10, "2026-03-19T10:00:00Z", "B") == 9.524


def test_negative_prices_cap_and_winter_peak():
    assert convert(-5, "2026-09-19T10:00:00Z", "P") < 0
    assert convert(120, "2026-09-19T10:00:00Z", "P") == 100
    assert convert(30, "2026-12-19T15:00:00Z", "A") == 30
    assert convert(30, "2026-12-19T16:00:00Z", "A") == 31


def test_temporary_zero_vat_uses_london_dates_and_restores_five_percent():
    assert convert(30, "2026-09-30T15:00:00Z", "A") == 31.05
    assert convert(30, "2026-10-01T15:00:00Z", "A") == 31
    assert convert(10, "2026-09-30T22:30:00Z", "B") == 9.357
    assert convert(10, "2026-09-30T23:00:00Z", "B") == 9.365
    assert convert(30, "2027-03-31T15:00:00Z", "A") == 31
    assert convert(10, "2027-03-31T23:00:00Z", "B") == 9.357
    assert convert(30, "2027-04-01T15:00:00Z", "A") == 31.05


def test_official_rates_are_never_replaced_with_converted_prices():
    slots = [
        {"start": "2026-09-19T10:00:00+00:00", "price": 10, "status": "published"},
        {"start": "2026-09-19T10:30:00+00:00", "price": 10, "status": "published"},
        {"start": "2026-09-20T10:00:00+00:00", "price": 10, "status": "predicted"},
    ]
    result = forecasts(slots, {"B": {slots[0]["start"]: 9.35}})
    assert result["B"]["prices"] == [9.35, None, 9.357]
    assert set(forecasts(slots, {})) == {"G"}
