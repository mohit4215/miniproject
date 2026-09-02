"""End-to-end smoke tests. Run: python -m pytest tests -v (or python tests/test_smoke.py)"""
import os

os.environ.setdefault("DEV_AUTH", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_smoke.db")
os.environ.setdefault("CONTEXT_BUDGET_TOKENS", "2000")
os.environ.setdefault("ADMIN_UIDS", "alice")

if os.path.exists("test_smoke.db"):
    os.remove("test_smoke.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.rooms import manager  # noqa: E402

init_db()
client = TestClient(app)
H1 = {"X-Dev-UID": "alice"}
H2 = {"X-Dev-UID": "bob"}


def ws_connect(code: str, uid: str, name: str):
    return client.websocket_connect(f"/api/rooms/ws/{code}?uid={uid}&name={name}")


def recv_until(ws, wanted_type, max_msgs=30, pred=None):
    for _ in range(max_msgs):
        msg = ws.receive_json()
        if msg.get("type") == wanted_type and (pred is None or pred(msg)):
            return msg
    raise AssertionError(f"never received {wanted_type}")


def test_health():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_room_flow_with_violation_and_awards():
    code = client.post("/api/rooms", json={"name": "Test room", "duration_default": 25},
                       headers=H1).json()["code"]

    with ws_connect(code, "alice", "Alice") as wa:
        state = recv_until(wa, "room_state")
        assert state["you"]["user_id"] == "alice"
        assert state["host_id"] == "alice"

        with ws_connect(code, "bob", "Bob") as wb:
            recv_until(wb, "room_state")
            members_msg = recv_until(wa, "presence",
                                     pred=lambda m: {x["user_id"] for x in m["members"]} == {"alice", "bob"})
            assert {m["user_id"] for m in members_msg["members"]} == {"alice", "bob"}

            # non-host cannot start
            wb.send_json({"type": "start", "duration_min": 25})
            err = recv_until(wb, "error", max_msgs=4)
            assert "host" in err["detail"].lower()

            # host starts a tiny session
            wa.send_json({"type": "start", "duration_min": 1})
            started = recv_until(wa, "timer_started")
            assert manager.state(code).phase == "running"

            # bob violates focus once
            wb.send_json({"type": "violation"})
            viol = recv_until(wb, "violation")
            assert viol["count"] == 1

            # chat broadcast reaches everyone
            wa.send_json({"type": "chat", "text": "stay focused"})
            chat = recv_until(wb, "chat")
            assert chat["text"] == "stay focused"

            # finish early → awards for both members
            wa.send_json({"type": "finish_early"})
            done_a = recv_until(wa, "session_complete")
            done_b = recv_until(wb, "session_complete")
            by_user = {r["user_id"]: r for r in done_a["results"]}
            assert set(by_user) == {"alice", "bob"}
            assert by_user["bob"]["violations"] == 1
            assert by_user["alice"]["points"] > by_user["bob"]["points"]
            assert done_b == done_a


def test_notebook_quiz_flow():
    nb = client.post("/api/notebooks", json={"title": "Biology"}, headers=H1).json()
    client.post(f"/api/notebooks/{nb['id']}/sources",
                json={"title": "Cells",
                      "text": "Mitochondria are the powerhouse of the cell. "
                              "They produce ATP through cellular respiration. "
                              "Ribosomes build proteins. The nucleus stores DNA."},
                headers=H1)

    summary = client.post(f"/api/notebooks/{nb['id']}/summarize", headers=H1).json()
    assert summary["summary"]
    assert summary["stats"]["fidelity"] in ("full", "selected", "truncated")

    answer = client.post(f"/api/notebooks/{nb['id']}/chat",
                         json={"message": "What produces ATP?"}, headers=H1).json()
    assert answer["answer"]

    quiz = client.post(f"/api/notebooks/{nb['id']}/quiz?num_questions=3", headers=H1).json()
    assert len(quiz["questions"]) >= 3
    assert all("answer_index" not in q for q in quiz["questions"])  # answers hidden

    answers = [0] * len(quiz["questions"])
    result = client.post(f"/api/notebooks/quizzes/{quiz['quiz_id']}/submit",
                         json={"answers": answers}, headers=H1).json()
    assert result["max"] == len(answers)
    assert result["points"]["delta"] >= 0

    # other user cannot see alice's notebook
    assert client.get(f"/api/notebooks/{nb['id']}", headers=H2).status_code == 404


def test_notes_crud_and_gamify():
    note = client.post("/api/notes",
                       json={"title": "ATP facts", "content": "**ATP** = energy currency",
                             "tags": "bio, energy"}, headers=H1).json()
    assert note["points"]["delta"] > 0

    found = client.get("/api/notes?q=atp", headers=H1).json()
    assert any(n["title"] == "ATP facts" for n in found)

    client.put(f"/api/notes/{note['id']}",
               json={"title": "ATP facts v2", "content": "updated", "tags": "bio"},
               headers=H1)
    got = client.get(f"/api/notes/{note['id']}", headers=H1).json()
    assert got["title"] == "ATP facts v2" and got["content"] == "updated"

    profile = client.get("/api/gamify/profile", headers=H1).json()
    assert profile["points"] > 0
    assert profile["current_streak"] >= 1
    assert profile["level"]["level"] >= 1

    lb = client.get("/api/gamify/leaderboard", headers=H1).json()
    assert lb and lb[0]["rank"] == 1


def test_admin_dashboard():
    profile = client.get("/api/gamify/profile", headers=H1).json()
    assert profile["is_admin"] is True

    # non-admin is locked out
    assert client.get("/api/admin/overview", headers=H2).status_code == 403
    assert client.get("/api/admin/users", headers=H2).status_code == 403

    ov = client.get("/api/admin/overview", headers=H1).json()
    assert ov["users"] >= 2
    assert {"notes", "rooms", "online_now", "sessions_running"} <= set(ov)

    users = client.get("/api/admin/users?q=bob", headers=H1).json()
    bob = next(u for u in users if u["id"] == "bob")
    assert "points" in bob and "is_admin" in bob

    upd = client.patch(f"/api/admin/users/{bob['id']}",
                       json={"display_name": "Bobby", "is_admin": False},
                       headers=H1).json()
    assert upd["display_name"] == "Bobby" and upd["is_admin"] is False
    # cannot revoke own admin, cannot delete self
    assert client.patch("/api/admin/users/alice", json={"is_admin": False},
                        headers=H1).status_code == 400
    assert client.delete("/api/admin/users/alice", headers=H1).status_code == 400

    pts = client.post(f"/api/admin/users/bob/points",
                      json={"delta": -50, "reason": "test penalty"}, headers=H1).json()
    assert pts["delta"] == -50

    # room management: create as non-admin bob, administer as alice
    code = client.post("/api/rooms", json={"name": "Admin test"}, headers=H2).json()["code"]
    rooms = client.get("/api/admin/rooms", headers=H1).json()
    row = next(r for r in rooms if r["code"] == code)
    assert row["phase"] in ("idle", "running")
    # upsert_user re-syncs display_name from auth claims on every request,
    # so the earlier rename is overwritten back to the uid-derived name
    assert row["host_name"] == "bob"

    end = client.post(f"/api/admin/rooms/{code}/end", headers=H1).json()
    assert end["ok"] is True and end["finalized"] is False  # idle room → no finalize

    assert client.delete(f"/api/admin/rooms/{code}", headers=H1).json()["ok"] is True
    assert client.get(f"/api/rooms/{code}", headers=H1).status_code == 404

    # user deletion removes content but keeps self-safe guards
    carol_h = {"X-Dev-UID": "carol"}
    client.post("/api/notes", json={"title": "temp", "content": "x"}, headers=carol_h)
    assert client.delete("/api/admin/users/carol", headers=H1).json()["ok"] is True
    notes_left = client.get("/api/notes", headers=carol_h).json()  # re-created fresh on upsert
    assert all(n["title"] != "temp" for n in notes_left)


if __name__ == "__main__":
    import traceback

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    raise SystemExit(1 if failures else 0)
