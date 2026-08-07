"""Closing a stocktake must act on what it found.

Before this, a count could prove a container absent and the app would keep
showing it as present -- the report was unactionable. Closing now flags missing
containers so every "is it here" view (map, contents, dashboard) agrees with the
count.
"""


def _open_session(member, db):
    """Start a count over the box that holds the first container."""
    box_id = db.execute("SELECT box_id FROM container LIMIT 1").fetchone()[0]
    r = member.post("/api/counts", json={"location_id": box_id, "name": "test count"})
    assert r.status_code == 200, r.text
    return r.json()


def test_close_flags_uncounted_containers_missing(member, db):
    session = _open_session(member, db)
    sid = session["id"]
    lines = member.get(f"/api/counts/{sid}").json()["lines"]
    assert lines, "count session should enumerate containers"
    cid = lines[0]["container_id"]
    assert db.execute(
        "SELECT status FROM container WHERE id = ?", (cid,)
    ).fetchone()[0] == "in_use"

    # Close without counting anything: every line becomes missing.
    assert member.post(f"/api/counts/{sid}/close").status_code == 200

    assert db.execute(
        "SELECT status FROM container WHERE id = ?", (cid,)
    ).fetchone()[0] == "missing"


def test_found_containers_are_left_alone(member, db):
    """Only lines the count could not account for may be flagged."""
    session = _open_session(member, db)
    sid = session["id"]
    lines = member.get(f"/api/counts/{sid}").json()["lines"]
    cid = lines[0]["container_id"]
    # Mark this one found (the scan endpoint resolves item codes; here we are
    # testing the close logic, so set the line state directly).
    db.execute(
        "UPDATE count_line SET status = 'found', counted = expected WHERE id = ?",
        (lines[0]["id"],),
    )
    db.commit()
    member.post(f"/api/counts/{sid}/close")
    assert db.execute(
        "SELECT status FROM container WHERE id = ?", (cid,)
    ).fetchone()[0] == "in_use"


def test_missing_container_drops_out_of_present_counts(member, db):
    """The point of the write-back: "is it here" views must agree with the count.

    The item record still lists the container (flagged missing, which is what you
    want on the item's own page); what changes is that it no longer counts as
    physically present.
    """
    session = _open_session(member, db)
    sid = session["id"]
    lines = member.get(f"/api/counts/{sid}").json()["lines"]
    cid = lines[0]["container_id"]
    item_id = db.execute(
        """SELECT l.item_id FROM container c
             JOIN item_lot l ON l.id = c.item_lot_id WHERE c.id = ?""",
        (cid,),
    ).fetchone()[0]

    present_before = db.execute(
        "SELECT COUNT(*) FROM container WHERE status = 'in_use'"
    ).fetchone()[0]
    member.post(f"/api/counts/{sid}/close")
    present_after = db.execute(
        "SELECT COUNT(*) FROM container WHERE status = 'in_use'"
    ).fetchone()[0]
    assert present_after < present_before

    # Still visible on the item record, but flagged rather than silently present.
    shown = member.get(f"/api/items/{item_id}").json()["containers"]
    row = next(c for c in shown if c["id"] == cid)
    assert row["status"] == "missing"


def test_close_reports_per_item_discrepancies(member, db):
    """Quantities are never auto-adjusted; the count reports what to reconcile."""
    session = _open_session(member, db)
    sid = session["id"]
    detail = member.post(f"/api/counts/{sid}/close").json()
    disc = detail["discrepancies"]
    assert disc, "closing with unfound containers should report discrepancies"
    first = disc[0]
    # Enough context for a one-click "set actual quantity" without guessing math.
    for key in ("item_id", "item_name", "quantity_on_hand", "missing_containers"):
        assert key in first
    assert first["missing_containers"] >= 1
