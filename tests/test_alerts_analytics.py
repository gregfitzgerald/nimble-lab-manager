"""Alerts and analytics endpoints against the seeded DB.

Assertions are chosen to stay true regardless of the wall-clock date: seed
expiry dates in the past stay expired forever, and shape/consistency checks
replace anything that would drift as time moves on.
"""


# --------------------------------------------------------------------------- #
# dashboard (seeded counts that never drift)
# --------------------------------------------------------------------------- #
def test_dashboard_counts_and_recent_events(viewer):
    data = viewer.get("/api/dashboard").json()
    counts = data["counts"]
    assert counts["items"] == 20  # 21 seeded minus 1 deprecated (active only)
    assert counts["locations"] == 19
    assert counts["containers"] == 55  # 57 total minus 2 'empty'
    assert counts["misplaced"] == 4
    for key in ("expiring_soon", "expired", "low_stock"):
        assert counts[key] >= 0
    events = data["recent_events"]
    assert 0 < len(events) <= 10
    assert {"event_type", "item_name", "quantity", "occurred_at"} <= set(events[0])


# --------------------------------------------------------------------------- #
# alerts
# --------------------------------------------------------------------------- #
def test_alerts_expiring_shape_and_ordering(viewer):
    rows = viewer.get("/api/alerts/expiring", params={"days": 36500}).json()
    # every dated lot in seed.sql falls inside a 100-year window
    assert len(rows) == 19
    for r in rows:
        assert {"item_name", "lot_number", "expiry_date", "quantity",
                "days_left"} <= set(r)
    dates = [r["expiry_date"] for r in rows]
    assert dates == sorted(dates)
    # seed contains lots dated in the past -> permanently expired
    assert any(r["days_left"] < 0 for r in rows)


def test_alerts_expiring_window_zero_is_only_past_due(viewer):
    rows = viewer.get("/api/alerts/expiring", params={"days": 0}).json()
    assert rows, "seed has lots already past expiry"
    assert all(r["days_left"] <= 0 for r in rows)


def test_alerts_lowstock_math(viewer):
    rows = viewer.get("/api/alerts/lowstock").json()
    assert rows
    by_id = {r["item_id"]: r for r in rows}
    for r in rows:
        assert r["quantity_on_hand"] <= r["reorder_threshold"]
        assert r["suggested_order_qty"] >= 1
    # item 4 (Anti-GABA, 0 on hand, threshold 1, $320): target = max(2, 2) = 2
    gaba = by_id[4]
    assert gaba["suggested_order_qty"] == 2
    assert gaba["estimated_cost"] == 640.0


def test_alerts_misplaced_exact_seeded_set(viewer):
    rows = viewer.get("/api/alerts/misplaced").json()
    assert {r["container_id"] for r in rows} == {54, 55, 56, 57}
    for r in rows:
        assert {"container_id", "item_name", "actual", "expected"} <= set(r)
        for side in ("actual", "expected"):
            assert {"box", "row", "col"} <= set(r[side])
        assert (
            r["actual"]["box"], r["actual"]["row"], r["actual"]["col"]
        ) != (
            r["expected"]["box"], r["expected"]["row"], r["expected"]["col"]
        )
    c54 = next(r for r in rows if r["container_id"] == 54)
    assert c54["actual"] == {"box": "Box A1 (RNA)", "row": 7, "col": 8}
    assert c54["expected"] == {"box": "Box A2 (Abs)", "row": 1, "col": 1}


# --------------------------------------------------------------------------- #
# analytics
# --------------------------------------------------------------------------- #
def test_analytics_spend_monthly_and_cumulative(viewer):
    rows = viewer.get("/api/analytics/spend").json()
    assert [r["month"] for r in rows] == ["2026-04", "2026-05", "2026-06"]
    assert [r["monthly_spend"] for r in rows] == [524.0, 757.5, 748.5]
    assert [r["cumulative_spend"] for r in rows] == [524.0, 1281.5, 2030.0]
    # cumulative must be a running total of monthly
    running = 0.0
    for r in rows:
        running += r["monthly_spend"]
        assert abs(r["cumulative_spend"] - round(running, 2)) < 0.01


def test_analytics_colony_census(viewer):
    rows = viewer.get("/api/analytics/colony").json()
    census = {(r["strain"], r["sex"]): r["n_alive"] for r in rows}
    assert census == {
        ("C57BL/6J", "F"): 1,
        ("C57BL/6J", "M"): 2,
        ("CNTNAP2-KO", "M"): 1,
        ("Sprague-Dawley", "F"): 2,
        ("Sprague-Dawley", "M"): 1,
    }
    assert all(r["avg_age_weeks"] > 0 for r in rows)


def test_analytics_forecast_shape_and_consistency(viewer):
    rows = viewer.get("/api/analytics/forecast", params={"days": 90}).json()
    assert len(rows) == 21  # one row per inventory item
    for r in rows:
        assert {"item_id", "item_name", "quantity_on_hand", "avg_daily_use",
                "days_to_stockout"} <= set(r)
        assert r["avg_daily_use"] >= 0
        if r["avg_daily_use"] == 0:
            assert r["days_to_stockout"] is None
        else:
            # avg_daily_use is rounded to 3 decimals in the response while
            # days_to_stockout is computed from the unrounded rate, so allow
            # a small relative tolerance when cross-checking the two.
            expected = r["quantity_on_hand"] / r["avg_daily_use"]
            assert abs(r["days_to_stockout"] - expected) <= max(1.0, 0.05 * expected)


def test_analytics_usage_series_is_continuous(viewer):
    days = 30
    data = viewer.get("/api/analytics/usage", params={"days": days}).json()
    series = data["series"]
    assert len(series) == days
    assert data["item_name"] is None  # no item filter
    from datetime import date, timedelta

    dates = [s["date"] for s in series]
    start = date.fromisoformat(dates[0])
    assert dates == [(start + timedelta(days=i)).isoformat() for i in range(days)]
    assert all(s["quantity"] >= 0 for s in series)


def test_analytics_usage_item_filter(viewer):
    data = viewer.get(
        "/api/analytics/usage", params={"item_id": 7, "days": 14}
    ).json()
    assert data["item_name"] == "DMEM High Glucose"
    assert len(data["series"]) == 14

    missing = viewer.get(
        "/api/analytics/usage", params={"item_id": 99999, "days": 7}
    ).json()
    assert missing["item_name"] is None
    assert all(s["quantity"] == 0 for s in missing["series"])
