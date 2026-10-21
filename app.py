import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

load_dotenv()
from inetz.database import DB, DATABASE_URL, engine
from inetz.models import *

app = FastAPI(title="iNetz Recruitment", version="1.0")
app.mount("/assets", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="assets")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

def db_session():
    with DB() as session: yield session


def current_user(request: Request, db: Session = Depends(db_session)):
    token = request.cookies.get("inetz_session")
    if not token or "." not in token: raise HTTPException(401, "Sign in required")
    uid, signature = token.split(".", 1)
    secret = os.getenv("SESSION_SECRET", "local-development-secret-change-before-deploy-32-chars")
    expected = hmac.new(secret.encode(), uid.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected): raise HTTPException(401, "Session expired")
    try: user_id = int(uid)
    except ValueError: raise HTTPException(401, "Session expired")
    user = db.get(User, user_id)
    if not user or not user.active or user.role != "candidate": raise HTTPException(401, "Candidate account unavailable")
    return user


def require(user, roles):
    if user.role not in roles: raise HTTPException(403, "Insufficient permissions")


def view_attempt(a, internal=False):
    snapshot = json.loads(a.snapshot)
    data = {"round": a.round, "answers": json.loads(a.answers), "score": a.score, "max_score": len(snapshot), "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None, "pass_mark": a.pass_mark, "questions": [{k: v for k, v in item.items() if k != "answer"} for item in snapshot]}
    return data


def public_candidate(c, internal=False):
    d = {"id": c.id, "name": c.full_name, "email": c.email, "mobile": c.mobile, "role": c.role, "stage": c.stage, "created_at": c.created_at.isoformat()}
    return d


def ensure_attempt(db, c, r):
    a = db.scalar(select(Attempt).where(Attempt.candidate_id == c.id, Attempt.round == r))
    if not a:
        expected_stage = "Aptitude MCQ" if r == "aptitude" else "Technical MCQ"
        if c.stage != expected_stage: raise HTTPException(409, "This assessment round is not currently available")
        a = Attempt(candidate_id=c.id, round=r, snapshot=json.dumps(mcq_snapshot(r, c.role)), pass_mark=int(app.state.config["pass_marks"][r]))
        db.add(a); db.commit(); db.refresh(a)
    elif r == "technical" and not a.submitted_at and not json.loads(a.answers or "{}"):
        domain = technical_domain(c.role)
        snapshot = json.loads(a.snapshot)
        session = assessment_session(db, c.id, r)
        if domain and not any(item.get("domain") == domain for item in snapshot) and (not session or not session.started_at):
            a.snapshot = json.dumps(mcq_snapshot(r, c.role))
            db.commit()
    return a


def session_view(session):
    if not session: return {"started": False, "warning_count": 0, "violation_limit": None, "deadline_at": None, "submitted_reason": ""}
    return {"started": True, "warning_count": session.warning_count, "violation_limit": session.violation_limit, "deadline_at": utc(session.deadline_at).isoformat(), "submitted_reason": session.submission_reason, "finished": bool(session.finished_at)}


def assessment_session(db, candidate_id, round_name, lock=False):
    query = select(AssessmentSession).where(AssessmentSession.candidate_id == candidate_id, AssessmentSession.round == round_name)
    return db.scalar(query.with_for_update() if lock else query)


def start_assessment_session(db, c, round_name):
    existing = assessment_session(db, c.id, round_name)
    if existing:
        if existing.finished_at: raise HTTPException(409, "Assessment already submitted")
        return existing
    expected = {"aptitude": "Aptitude MCQ", "technical": "Technical MCQ"}[round_name]
    if c.stage != expected: raise HTTPException(409, "This assessment round is not currently available")
    started = now()
    duration = 30 if round_name == "aptitude" else 20
    session = AssessmentSession(candidate_id=c.id, round=round_name, started_at=started,
                                deadline_at=started + timedelta(minutes=duration),
                                violation_limit=app.state.config["violation_limit"])
    db.add(session); db.commit(); db.refresh(session)
    return session


def validate_answers(answers, max_questions):
    if any(not k.isdigit() or int(k) < 1 or int(k) > max_questions or v not in range(4) for k, v in answers.items()):
        raise HTTPException(422, "Invalid answer selection")


def finish_mcq(db, c, attempt, session, reason):
    if attempt.submitted_at: return
    answers = json.loads(attempt.answers)
    snapshot = json.loads(attempt.snapshot)
    bank = APTITUDE if attempt.round == "aptitude" else TECH
    attempt.score = sum(1 for i, item in enumerate(snapshot, 1) if answers.get(str(i)) == (item["answer"] if "answer" in item else bank[i - 1][2]))
    attempt.submitted_at = now()
    c.stage = "Technical MCQ" if attempt.round == "aptitude" else "Completed"
    session.finished_at = attempt.submitted_at
    session.submission_reason = reason
    db.commit()




@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    app.state.config = {"pass_marks": {"aptitude": 8, "technical": 8}, "violation_limit": 3}

@app.get("/api/health")
def health():
    try:
        with DB() as db: db.execute(select(1))
        return {"status": "ok", "database": "connected"}
    except Exception: raise HTTPException(503, "Database unavailable")


@app.post("/api/login")
def login(body: Login, response: Response, db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or user.role != "candidate" or not user.active or not hmac.compare_digest(user.password_hash, digest(body.password, user.salt)):
        raise HTTPException(401, "Email or password is incorrect")
    token_id = str(user.id); sig = hmac.new(os.getenv("SESSION_SECRET", "local-development-secret-change-before-deploy-32-chars").encode(), token_id.encode(), hashlib.sha256).hexdigest()
    response.set_cookie("inetz_session", token_id + "." + sig, httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=43200)
    return {"id": user.id, "name": user.name, "role": user.role}


@app.post("/api/logout")
def logout(response: Response): response.delete_cookie("inetz_session", httponly=True, secure=COOKIE_SECURE, samesite="lax"); return {"ok": True}


@app.post("/api/candidate/register")
def candidate_signup(body: CandidateSignup, db: Session = Depends(db_session)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)) or db.scalar(select(Candidate).where(Candidate.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    salt = secrets.token_hex(16)
    candidate_user = User(email=email, name=body.name, role="candidate", salt=salt,
                          password_hash=digest(body.password, salt))
    db.add(candidate_user); db.flush()
    candidate = Candidate(user_id=candidate_user.id, full_name=body.name, email=email, mobile=body.mobile,
                          role=body.role.strip())
    db.add(candidate); db.commit()
    return {"ok": True, "message": "Your candidate account is ready. Sign in to continue."}


@app.get("/api/me")
def me(user=Depends(current_user), db: Session = Depends(db_session)):
    if user.role == "candidate":
        c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
        return {"id": user.id, "name": user.name, "role": user.role, "candidate": public_candidate(c) if c else None}
    return {"id": user.id, "name": user.name, "role": user.role}


@app.get("/api/session")
def session_status(request: Request, db: Session = Depends(db_session)):
    try: user = current_user(request, db)
    except HTTPException as error:
        if error.status_code == 401: return {"authenticated": False}
        raise
    return {"authenticated": True, **me(user, db)}



@app.get("/api/candidate/home")
def candidate_home(user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"]); c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if not c: raise HTTPException(404, "Candidate profile not found")
    attempts = db.scalars(select(Attempt).where(Attempt.candidate_id == c.id)).all()
    mcq_sessions = db.scalars(select(AssessmentSession).where(AssessmentSession.candidate_id == c.id,
                             AssessmentSession.round.in_(["aptitude", "technical"]))).all()
    stages = {"Aptitude MCQ": "aptitude", "Technical MCQ": "technical", "Completed": "result"}
    stage_key = stages.get(c.stage, "result")
    attempt_views = [view_attempt(a) for a in attempts]
    return {"candidate": public_candidate(c), "active_stage": stage_key, "attempts": attempt_views, "assessment_sessions": {item.round: session_view(item) for item in mcq_sessions}}


@app.get("/api/candidate/assessment/{round_name}")
def get_assessment(round_name: str, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Assessment not found")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id)); a = ensure_attempt(db, c, round_name)
    session = assessment_session(db, c.id, round_name)
    if session and not session.finished_at and utc(session.deadline_at) <= now():
        finish_mcq(db, c, a, session, "Assessment time expired.")
    return view_attempt(a) | {"session": session_view(session)}


@app.post("/api/candidate/assessment/{round_name}/start")
def begin_assessment(round_name: str, body: StartAssessment, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Assessment not found")
    if not body.acknowledged: raise HTTPException(422, "Acknowledge the assessment rules before starting")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id).with_for_update())
    attempt = ensure_attempt(db, c, round_name)
    if attempt.submitted_at: raise HTTPException(409, "Assessment already submitted")
    session = start_assessment_session(db, c, round_name)
    return session_view(session)


@app.post("/api/candidate/assessment/{round_name}/monitor")
def monitor_assessment(round_name: str, body: MonitorIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Assessment not found")
    if body.kind not in ("page_hidden", "focus_lost", "fullscreen_exit", "returned", "paste_blocked", "drag_blocked"):
        raise HTTPException(422, "Invalid monitoring event")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    session = assessment_session(db, c.id, round_name, lock=True)
    if not session: raise HTTPException(409, "Assessment has not started")
    existing = db.scalar(select(MonitoringEvent).where(MonitoringEvent.event_key == body.event_key))
    if existing:
        if existing.session_id != session.id: raise HTTPException(409, "Event key already used")
        return session_view(session) | {"auto_submitted": bool(session.submission_reason)}
    if session.finished_at: return session_view(session) | {"auto_submitted": True}
    if body.answers is not None:
        attempt = ensure_attempt(db, c, round_name)
        validate_answers(body.answers, len(json.loads(attempt.snapshot)))
        attempt.answers = json.dumps(body.answers)
    current = now()
    if body.kind in ("page_hidden", "focus_lost", "fullscreen_exit"):
        if not session.open_incident:
            recent_return = db.scalar(select(MonitoringEvent).where(MonitoringEvent.session_id == session.id,
                              MonitoringEvent.kind == "returned").order_by(MonitoringEvent.occurred_at.desc()).limit(1))
            if recent_return and recent_return.incident_id and current - utc(recent_return.occurred_at) < timedelta(milliseconds=1500):
                session.open_incident = recent_return.incident_id
                session.open_since = db.scalar(select(MonitoringEvent.occurred_at).where(MonitoringEvent.session_id == session.id,
                                        MonitoringEvent.incident_id == recent_return.incident_id).order_by(MonitoringEvent.occurred_at).limit(1))
            else:
                session.open_incident = secrets.token_hex(16)
                session.open_since = current
                session.warning_count += 1
        incident = session.open_incident
    elif body.kind == "returned":
        incident = session.open_incident
        if incident and session.open_since:
            elapsed = max(0, int((current - utc(session.open_since)).total_seconds() * 1000))
            for event in db.scalars(select(MonitoringEvent).where(MonitoringEvent.session_id == session.id, MonitoringEvent.incident_id == incident)).all():
                event.duration_ms = elapsed
            session.deadline_at = utc(session.deadline_at) + timedelta(milliseconds=elapsed)
        session.open_incident = ""; session.open_since = None
    else:
        incident = session.open_incident
    db.add(MonitoringEvent(session_id=session.id, event_key=body.event_key, incident_id=incident,
                           kind=body.kind, occurred_at=current))
    db.flush()
    if session.warning_count >= 3:
        reason = "Test ended after 3 warnings. Saved answers were submitted."
        finish_mcq(db, c, ensure_attempt(db, c, round_name), session, reason)
        return session_view(session) | {"auto_submitted": True}
    if utc(session.deadline_at) <= current:
        finish_mcq(db, c, ensure_attempt(db, c, round_name), session, "Assessment time expired.")
        return session_view(session) | {"auto_submitted": True}
    db.commit()
    return session_view(session) | {"auto_submitted": False}


@app.put("/api/candidate/assessment/{round_name}")
def save_assessment(round_name: str, body: SaveAnswers, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Assessment not found")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id)); a = ensure_attempt(db, c, round_name)
    session = assessment_session(db, c.id, round_name, lock=True)
    if not session: raise HTTPException(409, "Acknowledge the rules and start the assessment first")
    db.refresh(a)
    if a.submitted_at: raise HTTPException(409, "Submitted answers are locked")
    if session.finished_at: raise HTTPException(409, "Assessment already submitted")
    if session.open_incident: raise HTTPException(409, "Assessment paused. Return to fullscreen to continue.")
    if utc(session.deadline_at) <= now():
        finish_mcq(db, c, a, session, "Assessment time expired.")
        raise HTTPException(409, "Assessment time expired and answers were submitted")
    if (round_name == "aptitude" and c.stage != "Aptitude MCQ") or (round_name == "technical" and c.stage != "Technical MCQ"):
        raise HTTPException(409, "This assessment round is not currently available")
    validate_answers(body.answers, len(json.loads(a.snapshot)))
    a.answers = json.dumps(body.answers); db.commit(); return {"saved": True}


@app.post("/api/candidate/assessment/{round_name}/submit")
def submit_assessment(round_name: str, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Assessment not found")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id)); a = ensure_attempt(db, c, round_name)
    session = assessment_session(db, c.id, round_name, lock=True)
    if session: db.refresh(a)
    if a.submitted_at: return {"score": a.score, "submitted_at": a.submitted_at.isoformat(), "submission_reason": session.submission_reason if session else ""}
    if not session: raise HTTPException(409, "Acknowledge the rules and start the assessment first")
    if session.open_incident: raise HTTPException(409, "Assessment paused. Return to fullscreen to continue.")
    if (round_name == "aptitude" and c.stage != "Aptitude MCQ") or (round_name == "technical" and c.stage != "Technical MCQ"):
        raise HTTPException(409, "This assessment round is not currently available")
    reason = "Assessment time expired." if utc(session.deadline_at) <= now() else "Candidate submitted assessment."
    finish_mcq(db, c, a, session, reason)
    return {"score": a.score, "max_score": len(json.loads(a.snapshot)), "pass_mark": a.pass_mark, "submitted_at": a.submitted_at.isoformat(), "next_stage": c.stage, "submission_reason": session.submission_reason}




@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def missing_api(path: str):
    raise HTTPException(404, "API endpoint not found")


@app.get("/{path:path}", response_class=HTMLResponse)
def frontend(path: str):
    file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(file, encoding="utf-8") as f: return f.read()
