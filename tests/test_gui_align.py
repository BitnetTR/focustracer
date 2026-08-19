"""GUI API tests for the FR-KIO2-02 / FR-KIO2-03 endpoints.

The requirements ask for *"an API allowing a UI or a CLI to interact with the
system"*. The CLI side is covered by ``test_replay.py`` / ``test_align.py``;
this file pins the HTTP surface the web UI drives.
"""

import pytest

from focustracer import TraceContext

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def scale(n, factor):
    total = 0
    for i in range(n):
        total += i * factor
    return total


def _trace(tmp_path, name, fn):
    out = str(tmp_path / f"{name}.xml")
    with TraceContext(
        output_file=out, output_format="xml", schema_version="2.3",
        detail_level="detailed", target_functions=["scale"],
    ):
        fn()
    return out


@pytest.fixture(scope="module")
def client():
    from focustracer.gui.server import app
    return fastapi_testclient.TestClient(app)


@pytest.fixture
def traces(tmp_path):
    return {
        "a": _trace(tmp_path, "a", lambda: scale(4, 1)),
        "b": _trace(tmp_path, "b", lambda: scale(4, 10)),   # same flow, other values
        "c": _trace(tmp_path, "c", lambda: scale(9, 1)),    # longer flow => gaps
    }


# ── FR-KIO2-02: debugger stepping over HTTP ─────────────────────────────────


def test_replay_step_into_advances_one_line(client, traces):
    body = {"path": traces["a"], "seq": 0, "step_action": "into"}
    r = client.post("/api/trace/replay", json=body)
    assert r.status_code == 200
    assert r.json()["cursor"] == 1


def test_replay_step_action_backward(client, traces):
    r = client.post(
        "/api/trace/replay",
        json={"path": traces["a"], "seq": 3, "step_action": "into", "back": True},
    )
    assert r.json()["cursor"] == 2


# ── FR-KIO2-03: alignment over HTTP ─────────────────────────────────────────


def test_align_pair_returns_side_by_side_cursor(client, traces):
    r = client.post("/api/trace/align", json={"path": "", "paths": [traces["a"], traces["b"]], "seq": 3})
    assert r.status_code == 200
    data = r.json()
    assert data["mode"] == "pair"
    assert data["aligned"] is True
    assert data["a_seq"] == 3 and data["b_seq"] == 3
    assert data["a"]["current"]["line"] == data["b"]["current"]["line"]
    # identical control flow, different inputs => the delta names the divergent values
    names = {d["name"] for d in data["delta"]}
    assert "factor" in names
    assert "pairs" not in data["alignment"]      # summary only unless asked


def test_align_pair_reports_divergences(client, traces):
    r = client.post("/api/trace/align", json={"paths": [traces["a"], traces["c"]], "seq": 0})
    data = r.json()
    assert data["alignment"]["distance"] > 0
    assert data["divergences"]
    assert sum(d["length"] for d in data["divergences"]) == data["alignment"]["gaps"]


def test_align_set_returns_matrix_reference_and_outlier(client, traces):
    r = client.post(
        "/api/trace/align",
        json={"paths": [traces["a"], traces["b"], traces["c"]]},
    )
    data = r.json()
    assert data["mode"] == "set"
    assert data["reference"] in (0, 1)
    assert data["outlier"] == 2
    assert data["matrix"][0][0] == 0.0
    assert data["matrix"][0][2] == data["matrix"][2][0] > 0


def test_align_distance_endpoint(client, traces):
    r = client.post("/api/trace/align/distance", json={"paths": [traces["a"], traces["a"]]})
    assert r.json()["distance"] == 0        # invariant: identical traces => 0


def test_align_rejects_single_trace(client, traces):
    r = client.post("/api/trace/align", json={"paths": [traces["a"]]})
    assert r.status_code == 400


def test_align_missing_file_is_404(client, traces):
    r = client.post("/api/trace/align", json={"paths": [traces["a"], "no_such_trace.xml"]})
    assert r.status_code == 404
