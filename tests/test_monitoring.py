import json
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as system


@pytest.fixture
def clients(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    system.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(system, "engine", engine)
    monkeypatch.setattr(system, "DB", factory)
    system.app.state.config = {"pass_marks": {"aptitude": 8, "technical": 8},
                               "violation_limit": 3, "assessment_minutes": 60}
    with factory() as db:
        users = []
        for email in ("candidate1@example.com", "candidate2@example.com"):
            salt = uuid.uuid4().hex
            user = system.User(email=email, name=email.split("@")[0], role="candidate", salt=salt,
                               password_hash=system.digest("StrongPassword123", salt))
            db.add(user); db.flush(); users.append(user)
        db.add(system.Candidate(user_id=users[0].id, full_name="Candidate One", email=users[0].email,
                                role="Python Full Stack"))
        db.add(system.Candidate(user_id=users[1].id, full_name="Candidate Two", email=users[1].email,
                                role="Python Full Stack"))
        db.commit()
    def login(email):
        client = TestClient(system.app)
        response = client.post("/api/login", json={"email": email, "password": "StrongPassword123"})
        assert response.status_code == 200
        return client
    yield factory, login
    engine.dispose()


def event(client, kind, **extra):
    return client.post("/api/candidate/assessment/aptitude/monitor", json={"kind": kind, "event_key": uuid.uuid4().hex, **extra})


def test_focus_events_merge_and_submit_saved_answers(clients):
    factory, login = clients
    candidate = login("candidate1@example.com")
    assert candidate.put("/api/candidate/assessment/aptitude", json={"answers": {"1": 0}}).status_code == 409
    assert candidate.post("/api/candidate/assessment/aptitude/start", json={"acknowledged": False}).status_code == 422
    assert candidate.post("/api/candidate/assessment/aptitude/start", json={"acknowledged": True}).status_code == 200
    with factory() as db:
        aptitude = db.scalar(select(system.Attempt).where(system.Attempt.candidate_id == 1, system.Attempt.round == "aptitude"))
        correct_answers = {str(i + 1): item["answer"] for i, item in enumerate(json.loads(aptitude.snapshot)[:3])}
    assert candidate.put("/api/candidate/assessment/aptitude", json={"answers": correct_answers}).status_code == 200
    assert event(candidate, "page_hidden", answers={"1": 0, "2": 2}).json()["warning_count"] == 1
    assert event(candidate, "focus_lost").json()["warning_count"] == 1
    assert event(candidate, "fullscreen_exit").json()["warning_count"] == 1
    returned = event(candidate, "returned")
    assert returned.status_code == 200 and returned.json()["warning_count"] == 1
    assert event(candidate, "paste_blocked").json()["warning_count"] == 1
    with factory() as db:
        latest = db.scalar(select(system.MonitoringEvent).where(system.MonitoringEvent.kind == "returned"))
        latest.occurred_at -= timedelta(seconds=2)
        db.commit()
    second = event(candidate, "focus_lost", answers=correct_answers)
    assert second.json()["warning_count"] == 2
    assert second.json()["auto_submitted"] is False
    event(candidate, "returned")
    with factory() as db:
        latest = db.scalar(select(system.MonitoringEvent).where(system.MonitoringEvent.kind == "returned").order_by(system.MonitoringEvent.occurred_at.desc()))
        latest.occurred_at -= timedelta(seconds=2)
        db.commit()
    third = event(candidate, "fullscreen_exit", answers=correct_answers)
    assert third.json()["auto_submitted"] is True
    assert third.json()["submitted_reason"] == "Test ended after 3 warnings. Saved answers were submitted."
    attempt = candidate.get("/api/candidate/assessment/aptitude").json()
    assert attempt["answers"] == correct_answers
    assert attempt["score"] == 3 and attempt["submitted_at"]
    assert candidate.post("/api/candidate/assessment/aptitude/submit").json()["score"] == 3
    assert candidate.put("/api/candidate/assessment/aptitude", json={"answers": {"1": 1}}).status_code == 409
    with factory() as db:
        events = db.scalars(select(system.MonitoringEvent)).all()
        assert {item.kind for item in events} >= {"page_hidden", "focus_lost", "fullscreen_exit", "returned", "paste_blocked"}
        assert next(item for item in events if item.kind == "page_hidden").duration_ms is not None


def test_event_replay_does_not_add_warning(clients):
    _, login = clients
    candidate = login("candidate1@example.com")
    candidate.post("/api/candidate/assessment/aptitude/start", json={"acknowledged": True})
    payload = {"kind": "page_hidden", "event_key": uuid.uuid4().hex, "answers": {"1": 0}}
    first = candidate.post("/api/candidate/assessment/aptitude/monitor", json=payload).json()
    second = candidate.post("/api/candidate/assessment/aptitude/monitor", json=payload).json()
    assert first["warning_count"] == second["warning_count"] == 1


def test_technical_round_has_20_questions_and_20_minute_limit(clients):
    factory, login = clients
    with factory() as db:
        db.get(system.Candidate, 1).stage = "Technical MCQ"
        db.commit()
    candidate = login("candidate1@example.com")
    assessment = candidate.get("/api/candidate/assessment/technical").json()
    assert len(assessment["questions"]) == 20
    started = candidate.post("/api/candidate/assessment/technical/start", json={"acknowledged": True}).json()
    remaining_seconds = (system.utc(system.datetime.fromisoformat(started["deadline_at"])) - system.now()).total_seconds()
    assert 1190 <= remaining_seconds <= 1200
    with factory() as db:
        attempt = db.scalar(select(system.Attempt).where(system.Attempt.candidate_id == 1, system.Attempt.round == "technical"))
        answer_key = json.loads(attempt.snapshot)
        correct_answers = {str(i + 1): item["answer"] for i, item in enumerate(answer_key)}
    assert candidate.put("/api/candidate/assessment/technical", json={"answers": {"20": correct_answers["20"]}}).status_code == 200
    assert candidate.put("/api/candidate/assessment/technical", json={"answers": {"21": 0}}).status_code == 422
    assert candidate.put("/api/candidate/assessment/technical", json={"answers": correct_answers}).status_code == 200
    submitted = candidate.post("/api/candidate/assessment/technical/submit").json()
    assert submitted["score"] == 20 and submitted["max_score"] == 20


def test_removed_coding_stage_is_skipped_for_legacy_candidates(clients):
    factory, login = clients
    with factory() as db:
        candidate = db.get(system.Candidate, 1)
        candidate.stage = "Coding"
        db.commit()
    candidate = login("candidate1@example.com")
    home = candidate.get("/api/candidate/home")
    assert home.status_code == 200
    assert home.json()["active_stage"] == "result"
    with factory() as db:
        assert db.get(system.Candidate, 1).stage == "Completed"


def test_candidate_registration_through_technical_submission(clients, monkeypatch):
    monkeypatch.setattr(system, "sync_candidate_safely", lambda *args: True)
    factory, login = clients
    client = TestClient(system.app)
    email = f"candidate-{uuid.uuid4().hex[:10]}@example.com"
    registration = {
        "name": "New Candidate", "email": email, "password": "Pass1234",
        "mobile": "+1 555 123 4567", "role": "Python Full Stack",
        "degree": "B.Tech", "stream": "Computer Science", "candidate_status": "Fresher",
    }
    assert client.post("/api/candidate/register", json=registration | {"password": "short"}).status_code == 422
    assert client.post("/api/candidate/register", json=registration | {"mobile": ""}).status_code == 422
    registered = client.post("/api/candidate/register", json=registration)
    assert registered.status_code == 200
    duplicate = client.post("/api/candidate/register", json=registration)
    assert duplicate.status_code == 200
    assert duplicate.json() == {"ok": False, "account_exists": True}
    candidate = TestClient(system.app)
    assert candidate.post("/api/login", json={"email": email, "password": "Pass1234"}).status_code == 200
    home = candidate.get("/api/candidate/home")
    assert home.status_code == 200 and home.json()["active_stage"] == "aptitude"

    aptitude = candidate.get("/api/candidate/assessment/aptitude").json()
    assert len(aptitude["questions"]) == 15
    assert all("answer" not in question for question in aptitude["questions"])
    assert candidate.post("/api/candidate/assessment/aptitude/start", json={"acknowledged": True}).status_code == 200
    with factory() as db:
        attempt = db.scalar(select(system.Attempt).where(system.Attempt.round == "aptitude").join(system.Candidate).where(system.Candidate.email == email))
        aptitude_answers = {str(i + 1): item["answer"] for i, item in enumerate(json.loads(attempt.snapshot))}
    assert candidate.put("/api/candidate/assessment/aptitude", json={"answers": aptitude_answers}).status_code == 200
    aptitude_result = candidate.post("/api/candidate/assessment/aptitude/submit").json()
    assert aptitude_result["score"] == 15 and aptitude_result["max_score"] == 15
    home = candidate.get("/api/candidate/home").json()
    assert home["active_stage"] == "technical"
    assert home["attempts"][0]["score"] == 15
    assert "questions" not in home["attempts"][0]

    technical = candidate.get("/api/candidate/assessment/technical").json()
    assert len(technical["questions"]) == 20
    assert all("answer" not in question for question in technical["questions"])
    started = candidate.post("/api/candidate/assessment/technical/start", json={"acknowledged": True}).json()
    remaining_seconds = (system.datetime.fromisoformat(started["deadline_at"]) - system.now()).total_seconds()
    assert 1190 <= remaining_seconds <= 1200
    with factory() as db:
        attempt = db.scalar(select(system.Attempt).where(system.Attempt.round == "technical").join(system.Candidate).where(system.Candidate.email == email))
        technical_answers = {str(i + 1): item["answer"] for i, item in enumerate(json.loads(attempt.snapshot))}
    assert candidate.put("/api/candidate/assessment/technical", json={"answers": technical_answers}).status_code == 200
    technical_result = candidate.post("/api/candidate/assessment/technical/submit").json()
    assert technical_result["score"] == 20 and technical_result["max_score"] == 20
    assert candidate.post("/api/candidate/assessment/technical/submit").json() == technical_result
    assert candidate.get("/api/candidate/home").json()["active_stage"] == "result"
