import uuid
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as system


def test_signup_page_has_valid_phone_field_and_no_google_button():
    client = TestClient(system.app)
    signup_script = client.get("/assets/candidate_signup.js").text
    assert 'name="mobile" type="tel"' in signup_script
    assert 'pattern="[+0-9' not in signup_script
    assert 'googleLoginButton' not in signup_script
    assert "result.account_exists" in signup_script
    assert "Sign in with this email" in signup_script
    assert client.post("/api/login/google", json={"credential": "unused"}).status_code == 404


def test_registration_details_and_existing_database(monkeypatch):
    monkeypatch.setattr(system, "sync_candidate_safely", lambda *args: True)
    email = f"candidate-{uuid.uuid4().hex}@example.com"
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE candidates (id INTEGER PRIMARY KEY, user_id INTEGER, full_name VARCHAR(160), email VARCHAR(254), mobile VARCHAR(32), role VARCHAR(100), stage VARCHAR(48), created_at DATETIME)"))
    monkeypatch.setattr(system, "engine", engine)
    monkeypatch.setattr(system, "DB", sessionmaker(engine, expire_on_commit=False))
    system.startup()
    system.startup()
    columns = {column["name"] for column in inspect(engine).get_columns("candidates")}
    assert {"degree", "stream", "candidate_status", "area_of_interest"} <= columns

    client = TestClient(system.app)
    registration = {"name": "New Candidate", "email": email, "password": "secure-password-123",
                    "mobile": "+91 9876543210", "role": "Python Full Stack",
                    "degree": "B.Tech", "stream": "Computer Science", "candidate_status": "Fresher"}
    assert client.post("/api/candidate/register", json=registration | {"candidate_status": "Unknown"}).status_code == 422
    assert client.post("/api/candidate/register", json=registration | {"degree": "  "}).status_code == 422
    assert client.post("/api/candidate/register", json=registration | {"name": "  "}).status_code == 422
    assert client.post("/api/candidate/register", json=registration | {"role": "  "}).status_code == 422
    assert client.post("/api/candidate/register", json=registration | {"password": "short"}).status_code == 422
    with system.DB() as db:
        assert db.scalar(select(system.User).where(system.User.email == email)) is None
    assert client.post("/api/candidate/register", json=registration).status_code == 200
    duplicate = client.post("/api/candidate/register", json=registration)
    assert duplicate.status_code == 200
    assert duplicate.json() == {"ok": False, "account_exists": True}
    assert client.post("/api/logout").status_code == 200
    assert client.post("/api/login", json={"email": email, "password": registration["password"]}).status_code == 200
    profile = client.get("/api/me").json()["candidate"]
    for field in ("degree", "stream", "candidate_status"):
        assert profile[field] == registration[field]
    assert profile["area_of_interest"] is None
    assert "coding_questions" not in client.get("/api/candidate/home").json()
    assert client.get("/api/candidate/code/1").status_code == 404
    assert client.put("/api/candidate/code", json={"question_id": 1, "language": "python", "source": "pass"}).status_code == 404
    engine.dispose()


def test_daily_retake_preserves_previous_results(monkeypatch):
    email = f"retake-{uuid.uuid4().hex}@example.com"
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    system.Base.metadata.create_all(engine)
    monkeypatch.setattr(system, "DB", sessionmaker(engine, expire_on_commit=False))
    system.app.state.config = {"pass_marks": {"aptitude": 8, "technical": 8}, "violation_limit": 3}
    client = TestClient(system.app)
    registration = {"name": "Repeat Candidate", "email": email, "password": "secure-password-123", "mobile": "9876543210",
                    "role": "Python Full Stack", "degree": "B.Tech", "stream": "Computer Science",
                    "candidate_status": "Student"}
    assert client.post("/api/candidate/register", json=registration).status_code == 200
    assert client.post("/api/candidate/retake").status_code == 409

    finished = system.now()
    previous_questions = {}
    with system.DB() as db:
        candidate = db.scalar(select(system.Candidate).where(system.Candidate.email == email))
        candidate.stage = "Coding"
        for round_name, score in (("aptitude", 12), ("technical", 17)):
            snapshot = system.fresh_snapshot(db, candidate, round_name)
            previous_questions[round_name] = {item["question"] for item in snapshot}
            db.add(system.Attempt(candidate_id=candidate.id, round=round_name, snapshot=json.dumps(snapshot), answers='{"1": 0}',
                                  score=score, submitted_at=finished, pass_mark=8))
            session = system.AssessmentSession(candidate_id=candidate.id, round=round_name,
                                               started_at=finished - timedelta(minutes=10),
                                               deadline_at=finished + timedelta(minutes=20), finished_at=finished,
                                               warning_count=1, submission_reason="Candidate submitted assessment.")
            db.add(session)
            db.flush()
            db.add(system.MonitoringEvent(session_id=session.id, event_key=f"event-{round_name}",
                                          kind="focus_lost", occurred_at=finished))
        db.commit()

    assert client.get("/api/candidate/home").json()["candidate"]["stage"] == "Completed"
    assert client.post("/api/candidate/retake").status_code == 409
    monkeypatch.setattr(system, "now", lambda: finished + timedelta(days=1, seconds=1))
    assert client.post("/api/candidate/retake").json() == {"ready": True}
    assert client.post("/api/candidate/retake").status_code == 409
    home = client.get("/api/candidate/home").json()
    assert home["active_stage"] == "aptitude"
    assert home["attempts"] == []
    assert {item["score"] for item in home["history"]} == {12, 17}
    with system.DB() as db:
        archive = db.scalars(select(system.AssessmentHistory)).all()
        assert all(len(json.loads(item.details)["events"]) == 1 for item in archive)
    aptitude = client.get("/api/candidate/assessment/aptitude")
    assert aptitude.status_code == 200
    assert previous_questions["aptitude"].isdisjoint(item["question"] for item in aptitude.json()["questions"])
    assert client.post("/api/candidate/assessment/aptitude/start", json={"acknowledged": True}).status_code == 200
    with system.DB() as db:
        candidate = db.scalar(select(system.Candidate).where(system.Candidate.email == email))
        candidate.stage = "Technical MCQ"
        db.commit()
    technical = client.get("/api/candidate/assessment/technical")
    assert technical.status_code == 200
    assert previous_questions["technical"].isdisjoint(item["question"] for item in technical.json()["questions"])
    engine.dispose()


def test_simultaneous_daily_retakes_archive_only_once(monkeypatch, request):
    path = Path(f"retake_test_{uuid.uuid4().hex}.db")
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 10})
    request.addfinalizer(lambda: (engine.dispose(), path.unlink(missing_ok=True)))
    system.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(system, "DB", factory)
    finished = system.now() - timedelta(days=2)
    with factory() as db:
        salt = uuid.uuid4().hex
        user = system.User(email="retake@example.com", name="Retake", role="candidate", salt=salt,
                           password_hash=system.digest("secure-password-123", salt))
        db.add_all([user, system.QuestionPoolLock(id=1)])
        db.flush()
        candidate = system.Candidate(user_id=user.id, full_name="Retake", email=user.email,
                                     role="Python Full Stack", stage="Completed")
        db.add(candidate)
        db.flush()
        for round_name in ("aptitude", "technical"):
            db.add(system.Attempt(candidate_id=candidate.id, round=round_name, snapshot="[]",
                                  score=0, submitted_at=finished))
        db.commit()
    clients = [TestClient(system.app) for _ in range(2)]
    for client in clients:
        assert client.post("/api/login", json={"email": "retake@example.com", "password": "secure-password-123"}).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: client.post("/api/candidate/retake").status_code, clients))
    assert sorted(results) == [200, 409]
    with factory() as db:
        assert len(db.scalars(select(system.AssessmentHistory)).all()) == 2
        assert db.scalars(select(system.Attempt)).all() == []
