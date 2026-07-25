"""Location tree, floors, and the manager-only location CRUD.

Seed layout (seed.sql): Room 201 (id 1) contains -80C Freezer (10) ->
Shelf 1 (20) -> Box A1 (30, 9x9). Containers 54 and 55 sit in box 30 but
are expected elsewhere (misplaced). Box 32 holds containers 48-53 and 57.
"""


def _find(nodes, node_id):
    for n in nodes:
        if n["id"] == node_id:
            return n
        hit = _find(n["children"], node_id)
        if hit:
            return hit
    return None


# --------------------------------------------------------------------------- #
# read endpoints
# --------------------------------------------------------------------------- #
def test_locations_tree_shape(viewer):
    roots = viewer.get("/api/locations").json()
    assert {r["id"] for r in roots} == {1, 2}  # two rooms, both parentless
    room = _find(roots, 1)
    assert room["kind"] == "room"
    # drill: room 1 -> freezer 10 -> shelf 20 -> box 30
    freezer = _find(room["children"], 10)
    assert freezer and freezer["kind"] == "freezer"
    shelf = _find(freezer["children"], 20)
    assert shelf and shelf["kind"] == "shelf"
    box = _find(shelf["children"], 30)
    assert box and box["kind"] == "box"
    assert (box["capacity_rows"], box["capacity_cols"]) == (9, 9)


def test_location_detail_for_box_lists_containers(viewer):
    data = viewer.get("/api/locations/30").json()
    assert data["node"]["id"] == 30
    assert data["node"]["kind"] == "box"
    assert data["children"] == []
    containers = data["containers"]
    assert containers, "box 30 holds containers in seed.sql"
    for c in containers:
        for key in ("id", "row", "col", "status", "item_name", "lot_number",
                    "expiry_date", "misplaced", "expiry_flag"):
            assert key in c
        assert c["expiry_flag"] in {"ok", "expiring", "expired", "none"}
    flagged = {c["id"] for c in containers if c["misplaced"]}
    assert flagged == {54, 55}  # actual box 30, expected boxes 31/32


def test_location_detail_for_room_lists_children_not_containers(viewer):
    data = viewer.get("/api/locations/1").json()
    child_ids = {c["id"] for c in data["children"]}
    assert child_ids == {10, 11, 12, 13, 14}
    assert data["containers"] == []


def test_location_detail_404(viewer):
    assert viewer.get("/api/locations/99999").status_code == 404


def test_floors_shape(viewer):
    floors = viewer.get("/api/floors").json()
    assert len(floors) == 1
    floor = floors[0]
    assert floor["floor_id"] == 1
    assert floor["width"] == 1000 and floor["height"] == 1000
    assert floor["units"], "floor 1 has drawable units"
    for u in floor["units"]:
        assert u["map_x"] is not None
        assert u["floor_id"] == 1


# --------------------------------------------------------------------------- #
# manager-only CRUD
# --------------------------------------------------------------------------- #
def test_create_patch_delete_location_roundtrip(manager):
    created = manager.post(
        "/api/locations",
        json={"kind": "bench", "name": "  Test Bench  ", "parent_id": 1},
    )
    assert created.status_code == 200
    node = created.json()
    assert node["name"] == "Test Bench"  # trimmed
    assert node["parent_id"] == 1
    node_id = node["id"]

    patched = manager.patch(
        f"/api/locations/{node_id}", json={"name": "Renamed Bench", "map_x": 5.0}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed Bench"
    assert patched.json()["map_x"] == 5.0

    deleted = manager.delete(f"/api/locations/{node_id}")
    assert deleted.status_code == 200
    assert manager.get(f"/api/locations/{node_id}").status_code == 404


def test_create_box_keeps_grid_capacity_others_do_not(manager):
    box = manager.post(
        "/api/locations",
        json={"kind": "box", "name": "Box T1", "parent_id": 20,
              "capacity_rows": 5, "capacity_cols": 5},
    ).json()
    assert (box["capacity_rows"], box["capacity_cols"]) == (5, 5)

    bench = manager.post(
        "/api/locations",
        json={"kind": "bench", "name": "Bench T1", "parent_id": 1,
              "capacity_rows": 5, "capacity_cols": 5},
    ).json()
    assert bench["capacity_rows"] is None
    assert bench["capacity_cols"] is None


def test_create_location_validation(manager):
    assert manager.post(
        "/api/locations", json={"kind": "spaceship", "name": "X"}
    ).status_code == 400
    assert manager.post(
        "/api/locations", json={"kind": "room", "name": "   "}
    ).status_code == 400
    assert manager.post(
        "/api/locations", json={"kind": "room", "name": "X", "parent_id": 99999}
    ).status_code == 400


def test_patch_location_validation(manager):
    assert manager.patch("/api/locations/1", json={}).status_code == 400
    assert manager.patch("/api/locations/1", json={"kind": "nope"}).status_code == 400
    assert manager.patch("/api/locations/1", json={"name": ""}).status_code == 400
    assert manager.patch("/api/locations/1", json={"parent_id": 1}).status_code == 400
    assert manager.patch("/api/locations/99999", json={"name": "X"}).status_code == 404


def test_delete_location_with_children_is_400(manager):
    resp = manager.delete("/api/locations/10")  # freezer with shelves inside
    assert resp.status_code == 400
    assert "child" in resp.json()["detail"]


def test_delete_location_with_containers_is_400(manager):
    resp = manager.delete("/api/locations/32")  # box holding vials
    assert resp.status_code == 400
    assert "container" in resp.json()["detail"]


def test_location_crud_forbidden_below_manager(member, viewer):
    body = {"kind": "room", "name": "Nope"}
    assert member.post("/api/locations", json=body).status_code == 403
    assert viewer.post("/api/locations", json=body).status_code == 403
    assert member.patch("/api/locations/1", json={"name": "N"}).status_code == 403
    assert viewer.patch("/api/locations/1", json={"name": "N"}).status_code == 403
    assert member.delete("/api/locations/13").status_code == 403
    assert viewer.delete("/api/locations/13").status_code == 403
