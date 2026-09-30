import re

from .conftest import create_case


def test_home_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json == {"status": "ok"}


def test_normal_case_uses_safe_questionnaire(client):
    response = create_case(client)
    assert response.status_code == 201
    data = response.get_json()
    assert data["reference"].startswith("MPK-")
    assert data["status"] == "collecting"
    assert data["token"]
    assert data["ai_mode"] == "fallback"
    assert data["messages"][-1]["role"] == "assistant"
    assert "AI ไม่พร้อม" in data["messages"][-1]["content"]

    without_token = client.get(f"/api/cases/{data['id']}")
    assert without_token.status_code == 404
    with_token = client.get(
        f"/api/cases/{data['id']}", headers={"X-Case-Token": data["token"]}
    )
    assert with_token.status_code == 200


def test_safe_questionnaire_collects_extended_history(client):
    case = create_case(client).get_json()
    headers = {"X-Case-Token": case["token"]}
    latest = case
    for number in range(1, 11):
        response = client.post(
            f"/api/cases/{case['id']}/messages",
            headers=headers,
            json={"content": f"คำตอบข้อมูลสุขภาพข้อที่ {number}"},
        )
        assert response.status_code == 200
        latest = response.get_json()

    assert latest["status"] == "ready"
    assert len([item for item in latest["messages"] if item["role"] == "patient"]) == 11


def test_emergency_is_escalated_before_ai(client):
    response = create_case(client, "เจ็บแน่นหน้าอกรุนแรงและหายใจไม่ออก")
    data = response.get_json()
    assert data["status"] == "escalated"
    assert data["urgency"] == "emergency"
    assert data["ai_mode"] == "safety_rule"
    assert "1669" in data["messages"][-1]["content"]


def test_severe_pain_is_marked_urgent_and_interview_continues(client):
    response = create_case(client, "ปวดท้องมากจนทนไม่ไหว ระดับความปวด 9/10")
    data = response.get_json()
    assert response.status_code == 201
    assert data["status"] == "collecting"
    assert data["urgency"] == "urgent"
    assert "ตรวจโดยเร็ว" in data["messages"][-1]["content"]


def test_severe_pain_in_follow_up_answer_is_marked_urgent(client):
    case = create_case(client).get_json()
    response = client.post(
        f"/api/cases/{case['id']}/messages",
        headers={"X-Case-Token": case["token"]},
        json={"content": "ตอนนี้ปวดมากขึ้นจนเดินไม่ได้ ให้คะแนน 8/10"},
    )
    data = response.get_json()
    assert response.status_code == 200
    assert data["status"] == "collecting"
    assert data["urgency"] == "urgent"
    assert "ตรวจโดยเร็ว" in data["messages"][-1]["content"]


def test_direct_identifier_is_rejected(client):
    response = create_case(client, "ปวดท้อง โทร 0812345678")
    assert response.status_code == 400


def test_staff_login_and_review(client):
    case = create_case(client).get_json()
    login_page = client.get("/staff/login")
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
    login = client.post(
        "/staff/login",
        data={"csrf_token": csrf, "username": "nurse", "password": "correct-horse-battery"},
    )
    assert login.status_code == 302
    detail = client.get(f"/staff/cases/{case['id']}")
    assert detail.status_code == 200
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', detail.data).group(1).decode()
    review = client.post(
        f"/staff/cases/{case['id']}/review",
        data={"csrf_token": csrf, "urgency": "soon", "status": "ready"},
    )
    assert review.status_code == 302


def test_admin_can_create_staff_account(client):
    login_page = client.get("/staff/login")
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
    login = client.post(
        "/staff/login",
        data={"csrf_token": csrf, "username": "nurse", "password": "correct-horse-battery"},
    )
    assert login.status_code == 302

    users_page = client.get("/staff/users")
    assert users_page.status_code == 200
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', users_page.data).group(1).decode()
    created = client.post(
        "/staff/users",
        data={
            "csrf_token": csrf,
            "display_name": "พยาบาลทดสอบ",
            "username": "demo.staff",
            "role": "staff",
            "password": "DemoStaff2026!",
        },
    )
    assert created.status_code == 302

    client.post("/staff/logout", data={"csrf_token": csrf})
    login_page = client.get("/staff/login")
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', login_page.data).group(1).decode()
    staff_login = client.post(
        "/staff/login",
        data={"csrf_token": csrf, "username": "demo.staff", "password": "DemoStaff2026!"},
    )
    assert staff_login.status_code == 302
    assert client.get("/staff/users").status_code == 403
