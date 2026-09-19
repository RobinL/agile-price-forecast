from agile_forecast.regions import convert, forecasts


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
    assert convert(30, "2026-12-19T16:00:00Z", "A") == 31.05


def test_official_rates_are_never_replaced_with_converted_prices():
    slots = [
        {"start": "2026-09-19T10:00:00+00:00", "price": 10, "status": "published"},
        {"start": "2026-09-19T10:30:00+00:00", "price": 10, "status": "published"},
        {"start": "2026-09-20T10:00:00+00:00", "price": 10, "status": "predicted"},
    ]
    result = forecasts(slots, {"B": {slots[0]["start"]: 9.35}})
    assert result["B"]["prices"] == [9.35, None, 9.357]
    assert set(forecasts(slots, {})) == {"G"}
