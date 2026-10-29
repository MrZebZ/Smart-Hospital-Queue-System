import sqlite3
import time

import pytest

import app as A


@pytest.fixture
def clients(tmp_path, monkeypatch):
    """Fresh database per test; returns (patient_client, staff_client_for_hospital_1)."""
    monkeypatch.setattr(A, "DB", str(tmp_path / "test.db"))
    A.fails.clear()
    A.init_db()
    patient, staff = A.app.test_client(), A.app.test_client()
    r = staff.post("/api/login", json={"username": "hospital1", "password": "demo123"})
    assert r.status_code == 200
    return patient, staff


def reserve(c, hid=1, name="Ali", phone="03001234567"):
    return c.post("/api/reserve", json={"hospital_id": hid, "name": name, "phone": phone})


def test_healthz(clients):
    assert clients[0].get("/healthz").get_json() == {"status": "ok"}


def test_regular_ranking_uses_travel_plus_wait(clients):
    hs = clients[0].get("/api/hospitals?lat=33.99&lng=72.93").get_json()
    assert len(hs) == 5 and "lat" in hs[0]
    assert [h["total_min"] for h in hs] == sorted(h["total_min"] for h in hs)


def test_emergency_lists_only_er_nearest_first(clients):
    hs = clients[0].get("/api/hospitals?mode=emergency").get_json()
    assert hs and all(h["has_er"] for h in hs)
    assert [h["km"] for h in hs] == sorted(h["km"] for h in hs)


def test_dashboard_requires_login(clients):
    patient, _ = clients
    assert patient.get("/api/dashboard/1").status_code == 401
    assert patient.get("/dashboard").status_code == 302


def test_login_wrong_password_and_rate_limit(clients):
    c = A.app.test_client()
    for _ in range(5):
        assert c.post("/api/login", json={"username": "hospital1", "password": "x"}).status_code == 401
    assert c.post("/api/login", json={"username": "hospital1", "password": "demo123"}).status_code == 429


def test_staff_cannot_open_other_hospitals(clients):
    _, staff = clients
    assert staff.get("/api/dashboard/2").status_code == 403
    assert staff.get("/api/me").get_json()["hospital_id"] == 1


def test_reservation_numbers_and_validation(clients):
    patient, _ = clients
    assert reserve(patient).get_json()["number"] == 1
    assert reserve(patient, name="Sara", phone="03007654321").get_json()["number"] == 2
    assert reserve(patient).status_code == 409                       # same phone twice
    assert reserve(patient, name="", phone="1").status_code == 400   # bad input
    assert reserve(patient, hid=99, phone="03111111111").status_code == 404


def test_queue_advances_when_staff_calls_next(clients):
    patient, staff = clients
    t1 = reserve(patient).get_json()
    t2 = reserve(patient, name="Sara", phone="03007654321").get_json()
    assert patient.get(f"/api/token/{t2['id']}").get_json()["position"] == 2
    staff.post("/api/dashboard/1/next")
    assert patient.get(f"/api/token/{t1['id']}").get_json()["status"] == "served"
    assert patient.get(f"/api/token/{t2['id']}").get_json()["position"] == 1


def test_cancel(clients):
    patient, _ = clients
    t = reserve(patient).get_json()
    patient.post(f"/api/token/{t['id']}/cancel")
    assert patient.get(f"/api/token/{t['id']}").get_json()["status"] == "cancelled"
    assert reserve(patient).status_code == 200                        # may reserve again


def test_reservation_expires(clients):
    patient, _ = clients
    t = reserve(patient).get_json()
    con = sqlite3.connect(A.DB)
    con.execute("UPDATE tokens SET created=?", (time.time() - (A.TTL_MIN + 1) * 60,))
    con.commit()
    con.close()
    assert patient.get(f"/api/token/{t['id']}").get_json()["status"] == "expired"


def test_emergency_alert_flow(clients):
    patient, staff = clients
    assert patient.post("/api/emergency", json={"hospital_id": 1, "name": "Bilal", "eta_min": 8}).status_code == 200
    alerts = staff.get("/api/dashboard/1").get_json()["alerts"]
    assert len(alerts) == 1
    staff.post(f"/api/alerts/{alerts[0]['id']}/ack")
    assert staff.get("/api/dashboard/1").get_json()["alerts"] == []
    assert patient.post("/api/emergency", json={"hospital_id": 3, "name": "X"}).status_code == 404  # clinic, no ER


def test_camera_requires_key_or_staff_session(clients):
    patient, staff = clients
    assert patient.post("/api/dashboard/1/camera", json={"count": 5}).status_code == 401
    ok = patient.post("/api/dashboard/1/camera", json={"count": 5}, headers={"X-Camera-Key": A.CAMERA_KEY})
    assert ok.status_code == 200
    assert staff.get("/api/dashboard/1").get_json()["walk_in"] == 5


def test_settings_and_history(clients):
    _, staff = clients
    assert staff.post("/api/dashboard/1/service-time", json={"avg_min": 9}).get_json()["avg_min"] == 9
    assert isinstance(staff.get("/api/dashboard/1/history").get_json(), list)


def test_logout(clients):
    _, staff = clients
    staff.post("/api/logout")
    assert staff.get("/api/me").status_code == 401
