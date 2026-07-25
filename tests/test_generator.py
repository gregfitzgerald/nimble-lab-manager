"""generate_data.py: determinism and world invariants.

Runs the generator in-process (main(argv)) into temp DBs with a pinned seed
and anchor date, so nothing depends on the wall clock or the repo's lab.db.
"""

import sqlite3

import pytest

import generate_data

SEED = "123"
TODAY = "2026-07-04"

# Deterministic tables are compared column-for-column. app_user is compared on
# its stable projection only: PBKDF2 salts and created_at differ per run by
# design.
FULL_TABLES = [
    "staff", "protocols", "animals", "inventory", "item_lot",
    "container", "orders", "training", "usage_event", "location_node",
]


def _generate(db_path, extra=()):
    argv = ["--preset", "small", "--seed", SEED, "--today", TODAY,
            "--db", str(db_path), "--force", *extra]
    assert generate_data.main(argv) == 0


def _projection(db_path):
    conn = sqlite3.connect(db_path)
    try:
        out = {}
        for table in FULL_TABLES:
            out[table] = conn.execute(
                f"SELECT * FROM {table} ORDER BY 1"
            ).fetchall()
        out["app_user"] = conn.execute(
            "SELECT username, full_name, role, staff_id FROM app_user "
            "ORDER BY username"
        ).fetchall()
        return out
    finally:
        conn.close()


@pytest.fixture(scope="module")
def generated_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("gen") / "gen.db"
    _generate(path)
    return path


def test_two_runs_are_identical(generated_db, tmp_path):
    other = tmp_path / "gen2.db"
    _generate(other)
    a = _projection(generated_db)
    b = _projection(other)
    assert a.keys() == b.keys()
    for table in a:
        assert a[table] == b[table], f"table {table} differs between runs"
        assert a[table], f"table {table} is empty"


def test_on_hand_matches_lot_sums(generated_db):
    conn = sqlite3.connect(generated_db)
    try:
        bad = conn.execute(
            """SELECT i.item_id FROM inventory i
               WHERE i.quantity_on_hand <>
                     COALESCE((SELECT SUM(quantity) FROM item_lot l
                               WHERE l.item_id = i.item_id), 0)"""
        ).fetchall()
        negative = conn.execute(
            "SELECT COUNT(*) FROM item_lot WHERE quantity < 0"
        ).fetchone()[0]
    finally:
        conn.close()
    assert bad == [], f"on_hand != SUM(lots) for items {bad}"
    assert negative == 0


def test_demo_signal_guarantees(generated_db):
    conn = sqlite3.connect(generated_db)
    try:
        expired = conn.execute(
            "SELECT COUNT(*) FROM item_lot "
            "WHERE expiry_date IS NOT NULL AND expiry_date < ?",
            (TODAY,),
        ).fetchone()[0]
        misplaced = conn.execute(
            """SELECT COUNT(*) FROM container
               WHERE status = 'in_use' AND expected_box_id IS NOT NULL
                 AND (box_id <> expected_box_id OR row <> expected_row
                      OR col <> expected_col)"""
        ).fetchone()[0]
    finally:
        conn.close()
    assert expired >= 1, "generator must produce at least one expired lot"
    assert misplaced >= 1, "generator must produce at least one misplaced container"


def test_generated_db_has_four_app_users(generated_db):
    conn = sqlite3.connect(generated_db)
    try:
        users = conn.execute(
            "SELECT username, role FROM app_user ORDER BY username"
        ).fetchall()
    finally:
        conn.close()
    assert users == [
        ("admin", "admin"),
        ("manager", "manager"),
        ("member", "member"),
        ("viewer", "viewer"),
    ]


def test_containers_reference_real_boxes_and_unique_wells(generated_db):
    conn = sqlite3.connect(generated_db)
    try:
        orphans = conn.execute(
            """SELECT COUNT(*) FROM container c
               LEFT JOIN location_node n ON n.id = c.box_id
               WHERE n.id IS NULL OR n.kind <> 'box'"""
        ).fetchone()[0]
        dupes = conn.execute(
            """SELECT COUNT(*) FROM (
                   SELECT box_id, row, col FROM container
                   WHERE status = 'in_use'
                   GROUP BY box_id, row, col HAVING COUNT(*) > 1)"""
        ).fetchone()[0]
    finally:
        conn.close()
    assert orphans == 0
    assert dupes == 0, "two in_use containers may not share a physical well"


def test_refuses_to_clobber_without_force(tmp_path, capsys):
    path = tmp_path / "keep.db"
    _generate(path)
    rc = generate_data.main(
        ["--preset", "small", "--seed", SEED, "--today", TODAY, "--db", str(path)]
    )
    assert rc == 1  # exists and no --force


def test_rejects_bad_today(tmp_path):
    rc = generate_data.main(
        ["--db", str(tmp_path / "x.db"), "--today", "not-a-date"]
    )
    assert rc == 2
