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
    if not user or not user.active: raise HTTPException(401, "Account unavailable")
    return user


def require(user, roles):
    if user.role not in roles: raise HTTPException(403, "Insufficient permissions")


def candidate_access(db, user, candidate_id, *, responsibilities=None):
    c = db.get(Candidate, candidate_id)
    if not c: raise HTTPException(404, "Candidate not found")
    if user.role == "candidate":
        if c.user_id != user.id: raise HTTPException(404, "Candidate not found")
    elif user.role != "admin": raise HTTPException(403, "Insufficient permissions")
    return c


def audit(db, user, candidate_id, action):
    db.add(Audit(actor_id=user.id, candidate_id=candidate_id, action=action))


def view_attempt(a, internal=False):
    snapshot = json.loads(a.snapshot)
    data = {"round": a.round, "answers": json.loads(a.answers), "score": a.score, "max_score": len(snapshot) if a.round in ("aptitude", "technical") else None, "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None, "remarks": a.remarks if internal else "", "pass_mark": a.pass_mark, "questions": [{k: v for k, v in item.items() if k != "answer"} for item in snapshot] if a.round in ("aptitude", "technical") else None}
    if internal and a.round in ("aptitude", "technical"):
        bank = APTITUDE if a.round == "aptitude" else TECH
        data["answer_key"] = {str(i + 1): item["answer"] if "answer" in item else bank[i][2] for i, item in enumerate(snapshot)}
    return data


def public_candidate(c, internal=False):
    d = {"id": c.id, "name": c.full_name, "email": c.email, "mobile": c.mobile, "role": c.role, "stage": c.stage, "created_at": c.created_at.isoformat(), "final_decision": c.final_decision if internal else (c.released_result or "Awaiting result"), "tech_recommendation": c.tech_recommendation if internal else "", "communication_status": c.communication_status if internal else "", "release_feedback": c.release_feedback if not internal or c.released_result else ""}
    if internal: d["assigned_admin"] = c.assigned_admin
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
    expected = {"aptitude": "Aptitude MCQ", "technical": "Technical MCQ", "coding": "Coding"}[round_name]
    if c.stage != expected: raise HTTPException(409, "This assessment round is not currently available")
    started = now()
    duration = 30 if round_name == "aptitude" else 20 if round_name == "technical" else app.state.config["assessment_minutes"]
    session = AssessmentSession(candidate_id=c.id, round=round_name, started_at=started,
                                deadline_at=started + timedelta(minutes=duration),
                                violation_limit=app.state.config["violation_limit"])
    db.add(session); db.commit(); db.refresh(session)
    return session


def validate_answers(answers, max_questions):
    if any(not k.isdigit() or int(k) < 1 or int(k) > max_questions or v not in range(4) for k, v in answers.items()):
        raise HTTPException(422, "Invalid answer selection")


def finish_mcq(db, c, attempt, session, reason, actor):
    if attempt.submitted_at: return
    answers = json.loads(attempt.answers)
    snapshot = json.loads(attempt.snapshot)
    bank = APTITUDE if attempt.round == "aptitude" else TECH
    attempt.score = sum(1 for i, item in enumerate(snapshot, 1) if answers.get(str(i)) == (item["answer"] if "answer" in item else bank[i - 1][2]))
    attempt.submitted_at = now()
    c.stage = "Technical MCQ" if attempt.round == "aptitude" else "Technical HR"
    session.finished_at = attempt.submitted_at
    session.submission_reason = reason
    audit(db, actor, c.id, "Submitted " + attempt.round + ("; " + reason if reason else ""))
    db.commit()


def save_code_draft(db, c, question_id, language, source):
    if question_id not in (1, 2, 3) or language not in ("python", "java", "javascript") or len(source) > 60_000:
        raise HTTPException(422, "Invalid source, language or question")
    submission = db.scalar(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id, CodeSubmission.question_id == question_id).with_for_update())
    if not submission:
        submission = CodeSubmission(candidate_id=c.id, question_id=question_id, language=language, source=source,
                                    max_score=CODING[question_id - 1]["marks"])
        db.add(submission)
    if submission.submitted: raise HTTPException(409, "Submitted code is locked")
    submission.language = language; submission.source = source; submission.updated_at = now()
    db.flush()
    return submission


def finish_coding(db, c, session, reason, actor):
    if session.finished_at: return
    for q in CODING:
        sub = db.scalar(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id, CodeSubmission.question_id == q["id"]).with_for_update())
        if not sub:
            sub = CodeSubmission(candidate_id=c.id, question_id=q["id"], language="python", source="", max_score=q["marks"])
            db.add(sub); db.flush()
        if not sub.submitted:
            sub.submitted = True
            sub.status = "Awaiting review"; sub.score = None; sub.result = "{}"
    session.finished_at = now(); session.submission_reason = reason
    audit(db, actor, c.id, "Submitted coding" + ("; " + reason if reason else ""))
    db.commit()


@app.on_event("startup")
def startup():
    Base.metadata.create_all(engine)
    app.state.config = {"pass_marks": {"aptitude": 8, "technical": 8, "coding": 60},
                        "violation_limit": 3, "assessment_minutes": 60}
    with DB() as db:
        for legacy_admin in db.scalars(select(User).where(User.role == "super_admin")).all():
            legacy_admin.role = "admin"
            legacy_admin.name = legacy_admin.name.replace("Super Admin", "Admin")
        db.flush()
        setting = db.get(AppSetting, "pass_marks")
        if setting:
            try: app.state.config["pass_marks"].update(json.loads(setting.value))
            except ValueError: pass
        for key in ("violation_limit", "assessment_minutes"):
            saved = db.get(AppSetting, key)
            if saved:
                try: app.state.config[key] = int(saved.value)
                except ValueError: pass
        email = os.getenv("ADMIN_EMAIL", "admin@example.com").lower()
        if not db.scalar(select(User).where(User.email == email)):
            password = os.getenv("ADMIN_PASSWORD", "ChangeThis!123")
            salt = secrets.token_hex(16)
            db.add(User(email=email, name="iNetz Admin", role="admin", responsibilities="[]", salt=salt, password_hash=digest(password, salt)))
            db.commit()
        for submission in db.scalars(select(CodeSubmission).where(
                CodeSubmission.submitted == True,
                CodeSubmission.status.in_(("Queued", "Running", "Failed", "Connection required")))).all():
            submission.status = "Awaiting review"
            submission.score = None
            submission.result = "{}"
        for candidate in db.scalars(select(Candidate).where(Candidate.stage == "Coding")).all():
            candidate.stage = "Technical HR"
            session = assessment_session(db, candidate.id, "coding")
            if session and not session.finished_at:
                session.finished_at = now()
                session.submission_reason = "Coding round removed."
        db.commit()


@app.get("/api/health")
def health():
    try:
        with DB() as db: db.execute(select(1))
        return {"status": "ok", "database": "connected"}
    except Exception: raise HTTPException(503, "Database unavailable")


@app.post("/api/login")
def login(body: Login, response: Response, db: Session = Depends(db_session)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if not user or not user.active or not hmac.compare_digest(user.password_hash, digest(body.password, user.salt)):
        raise HTTPException(401, "Email or password is incorrect")
    token_id = str(user.id); sig = hmac.new(os.getenv("SESSION_SECRET", "local-development-secret-change-before-deploy-32-chars").encode(), token_id.encode(), hashlib.sha256).hexdigest()
    response.set_cookie("inetz_session", token_id + "." + sig, httponly=True, secure=COOKIE_SECURE, samesite="lax", max_age=43200)
    return {"id": user.id, "name": user.name, "role": user.role, "responsibilities": json.loads(user.responsibilities or "[]")}


@app.post("/api/logout")
def logout(response: Response): response.delete_cookie("inetz_session", httponly=True, secure=COOKIE_SECURE, samesite="lax"); return {"ok": True}


@app.post("/api/candidate/register")
def candidate_signup(body: CandidateSignup, db: Session = Depends(db_session)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)) or db.scalar(select(Candidate).where(Candidate.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    salt = secrets.token_hex(16)
    candidate_user = User(email=email, name=body.name, role="candidate", responsibilities="[]", salt=salt,
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
    return {"id": user.id, "name": user.name, "role": user.role, "responsibilities": json.loads(user.responsibilities or "[]")}


@app.get("/api/session")
def session_status(request: Request, db: Session = Depends(db_session)):
    try: user = current_user(request, db)
    except HTTPException as error:
        if error.status_code == 401: return {"authenticated": False}
        raise
    return {"authenticated": True, **me(user, db)}


@app.post("/api/admin-request")
def request_admin_account(body: AdminSignup, db: Session = Depends(db_session)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with that email already exists")
    salt = secrets.token_hex(16)
    user = User(email=email, name=body.name, role="admin", responsibilities="[]", active=False,
                salt=salt, password_hash=digest(body.password, salt))
    db.add(user); db.commit()
    return {"ok": True, "message": "Admin access requested. An Admin must approve your account."}


@app.post("/api/redeem-invitation")
def redeem_invitation(body: Redeem, db: Session = Depends(db_session)):
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash))
    if not invitation or invitation.redeemed_at or utc(invitation.expires_at) < now(): raise HTTPException(410, "Invitation has expired or was already used")
    c = db.get(Candidate, invitation.candidate_id)
    if not c: raise HTTPException(404, "Candidate application not found")
    if c.user_id is not None: raise HTTPException(409, "This candidate account has already been activated")
    email = c.email.lower()
    if db.scalar(select(User).where(User.email == email)): raise HTTPException(409, "An account with this email already exists")
    salt = secrets.token_hex(16); user = User(email=email, name=c.full_name, role="candidate", responsibilities="[]", salt=salt, password_hash=digest(body.password, salt))
    db.add(user); db.flush(); c.user_id=user.id; invitation.redeemed_at=now(); db.commit()
    return {"ok": True, "message": "Candidate account activated. Sign in with your registered email and new password."}


@app.get("/api/candidate/home")
def candidate_home(user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"]); c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if not c: raise HTTPException(404, "Candidate profile not found")
    attempts = db.scalars(select(Attempt).where(Attempt.candidate_id == c.id)).all()
    code = db.scalars(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id)).all()
    coding_session = assessment_session(db, c.id, "coding")
    if c.stage == "Coding":
        c.stage = "Technical HR"
        if coding_session and not coding_session.finished_at:
            coding_session.finished_at = now()
            coding_session.submission_reason = "Coding round removed."
        db.commit()
    mcq_sessions = db.scalars(select(AssessmentSession).where(AssessmentSession.candidate_id == c.id,
                             AssessmentSession.round.in_(["aptitude", "technical"]))).all()
    stages = {"Aptitude MCQ": "aptitude", "Technical MCQ": "technical", "Technical HR": "interview", "General HR": "decision", "Candidate Communication": "result"}
    stage_key = stages.get(c.stage, "result")
    attempt_views = [view_attempt(a) for a in attempts]
    return {"candidate": public_candidate(c), "active_stage": stage_key, "attempts": attempt_views, "assessment_sessions": {item.round: session_view(item) for item in mcq_sessions}, "coding_session": session_view(coding_session), "coding": [{"question_id": s.question_id, "language": s.language, "source": s.source if s.submitted else "", "status": s.status if s.submitted else "Draft saved", "score": s.score, "max_score": s.max_score, "result": json.loads(s.result) if s.submitted else {}} for s in code], "coding_questions": [{k: v for k, v in q.items() if k not in ("tests", "test_cases")} for q in CODING] if c.stage in ("Coding", "Technical HR", "General HR", "Candidate Communication") else []}


@app.get("/api/candidate/assessment/{round_name}")
def get_assessment(round_name: str, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Assessment not found")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id)); a = ensure_attempt(db, c, round_name)
    session = assessment_session(db, c.id, round_name)
    if session and not session.finished_at and utc(session.deadline_at) <= now():
        finish_mcq(db, c, a, session, "Assessment time expired.", user)
    return view_attempt(a) | {"session": session_view(session)}


@app.post("/api/candidate/assessment/{round_name}/start")
def begin_assessment(round_name: str, body: StartAssessment, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Assessment not found")
    if not body.acknowledged: raise HTTPException(422, "Acknowledge the assessment rules before starting")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id).with_for_update())
    if round_name != "coding":
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
    if round_name == "coding" and body.question_id is not None and body.language and body.source is not None:
        submitted = db.scalar(select(CodeSubmission.submitted).where(
            CodeSubmission.candidate_id == c.id, CodeSubmission.question_id == body.question_id))
        if not submitted:
            save_code_draft(db, c, body.question_id, body.language, body.source)
    elif round_name != "coding" and body.answers is not None:
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
        if round_name == "coding":
            finish_coding(db, c, session, reason, user)
        else:
            finish_mcq(db, c, ensure_attempt(db, c, round_name), session, reason, user)
        return session_view(session) | {"auto_submitted": True}
    if utc(session.deadline_at) <= current:
        if round_name == "coding":
            finish_coding(db, c, session, "Assessment time expired.", user)
        else: finish_mcq(db, c, ensure_attempt(db, c, round_name), session, "Assessment time expired.", user)
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
        finish_mcq(db, c, a, session, "Assessment time expired.", user)
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
    finish_mcq(db, c, a, session, reason, user)
    return {"score": a.score, "max_score": len(json.loads(a.snapshot)), "pass_mark": a.pass_mark, "submitted_at": a.submitted_at.isoformat(), "next_stage": c.stage, "submission_reason": session.submission_reason}


@app.get("/api/candidate/code/{question_id}")
def get_code(question_id: int, language: str = "python", user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if question_id not in (1, 2, 3) or language not in ("python", "java", "javascript"): raise HTTPException(404, "Question or language not found")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if c.stage != "Coding": raise HTTPException(409, "Coding round is not currently available")
    s = db.scalar(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id, CodeSubmission.question_id == question_id))
    q = {k: v for k, v in CODING[question_id - 1].items() if k != "tests"}
    return {"question": q, "language": language, "source": s.source if s and s.language == language else starter(question_id, language), "status": s.status if s else "Not submitted", "score": s.score if s and s.submitted else None, "result": json.loads(s.result) if s and s.submitted else {}}


@app.put("/api/candidate/code")
def save_code(body: CodeIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if c.stage != "Coding": raise HTTPException(409, "Coding round is not currently available")
    session = assessment_session(db, c.id, "coding", lock=True)
    if not session: raise HTTPException(409, "Acknowledge the rules and start the coding assessment first")
    if session.finished_at: raise HTTPException(409, "Coding assessment already submitted")
    if session.open_incident: raise HTTPException(409, "Assessment paused. Return to fullscreen to continue.")
    if utc(session.deadline_at) <= now():
        finish_coding(db, c, session, "Assessment time expired.", user)
        raise HTTPException(409, "Assessment time expired")
    save_code_draft(db, c, body.question_id, body.language, body.source)
    db.commit(); return {"saved": True}


@app.post("/api/candidate/code/{question_id}/submit")
def submit_code(question_id: int, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["candidate"])
    if question_id not in (1, 2, 3): raise HTTPException(404, "Question not found")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id)); s = db.scalar(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id, CodeSubmission.question_id == question_id))
    session = assessment_session(db, c.id, "coding", lock=True)
    if session and s: db.refresh(s)
    if s and s.submitted: return {"status": s.status, "submission_reason": session.submission_reason if session else ""}
    if c.stage != "Coding": raise HTTPException(409, "Coding round is not currently available")
    if not session: raise HTTPException(409, "Acknowledge the rules and start the coding assessment first")
    if session.finished_at: return {"status": s.status if s else "Awaiting review", "submission_reason": session.submission_reason}
    if session.open_incident: raise HTTPException(409, "Assessment paused. Return to fullscreen to continue.")
    if utc(session.deadline_at) <= now():
        finish_coding(db, c, session, "Assessment time expired.", user)
        return {"status": "Awaiting review", "submission_reason": session.submission_reason}
    if not s or not s.source: raise HTTPException(400, "Save a solution before submitting")
    s.submitted = True; s.status = "Awaiting review"; s.score = None; s.result = "{}"
    audit(db, user, c.id, "Submitted coding question " + str(question_id))
    others = db.scalars(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id)).all()
    if len(others) == 3 and all(x.submitted for x in others):
        session.finished_at = now(); session.submission_reason = "Candidate submitted assessment."
    db.commit()
    return {"status": "Awaiting review"}


@app.get("/api/portal/dashboard")
def dashboard(user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    q = select(Candidate)
    cs = db.scalars(q.order_by(Candidate.created_at.desc())).all()
    attempts = db.scalars(select(Attempt)).all(); codes = db.scalars(select(CodeSubmission).where(CodeSubmission.submitted == True)).all()
    return {"candidates": [public_candidate(c) for c in cs], "attempts": [view_attempt(a, True) | {"candidate_id": a.candidate_id} for a in attempts], "coding": [{"id": x.id, "candidate_id": x.candidate_id, "question_id": x.question_id, "language": x.language, "source": x.source, "status": x.status, "score": x.score, "max_score": x.max_score, "result": json.loads(x.result)} for x in codes], "counts": {"total": len(cs), "stages": {s: sum(1 for c in cs if c.stage == s) for s in ("Aptitude MCQ", "Technical MCQ", "Coding", "Technical HR", "General HR", "Candidate Communication")}, "coding_jobs": {"Awaiting review": sum(1 for x in codes if x.status == "Awaiting review")}, "awaiting_communication": sum(1 for c in cs if c.final_decision != "Awaiting decision" and not c.released_result)}}


@app.post("/api/admin/candidates")
def create_candidate(body: CandidateIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)) or db.scalar(select(Candidate).where(Candidate.email == email)): raise HTTPException(409, "An application already exists with that email")
    assignee = body.admin_id or user.id
    if assignee:
        target = db.get(User, assignee)
        if not target or target.role != "admin": raise HTTPException(422, "Assigned user must be an Admin")
    c = Candidate(full_name=body.name, email=email, mobile=body.mobile, role=body.role, assigned_admin=assignee)
    db.add(c); db.flush()
    raw_token = secrets.token_urlsafe(32)
    invitation = Invitation(token_hash=hashlib.sha256(raw_token.encode()).hexdigest(), candidate_id=c.id,
                           expires_at=now() + timedelta(days=7))
    db.add(invitation); audit(db, user, c.id, "Registered candidate"); db.commit(); db.refresh(c)
    return {"candidate": public_candidate(c, True), "candidate_login_url": "/setup-account?token=" + raw_token,
            "notice": "Share this single-use setup link with the candidate so they can set their own password."}


@app.put("/api/admin/candidates/{candidate_id}/assignment")
def assign_candidate(candidate_id: int, body: AssignIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    c = db.get(Candidate, candidate_id)
    if not c: raise HTTPException(404, "Candidate not found")
    if body.admin_id:
        assigned=db.get(User, body.admin_id)
        if not assigned or assigned.role != "admin": raise HTTPException(422, "Assigned user must be an Admin")
    c.assigned_admin=body.admin_id; audit(db,user,c.id,"Changed candidate assignment"); db.commit()
    return {"saved": True}


@app.get("/api/admin/candidates/{candidate_id}")
def candidate_report(candidate_id: int, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    c = candidate_access(db, user, candidate_id)
    
    attempts = db.scalars(select(Attempt).where(Attempt.candidate_id == c.id)).all()
    codes = db.scalars(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id)).all()
    interview = db.scalar(select(Interview).where(Interview.candidate_id == c.id))
    events = db.scalars(select(Audit).where(Audit.candidate_id == c.id).order_by(Audit.created_at)).all()
    sessions = db.scalars(select(AssessmentSession).where(AssessmentSession.candidate_id == c.id).order_by(AssessmentSession.started_at)).all()
    monitoring = []
    reviews = {item.round: item for item in db.scalars(select(MonitoringReview).where(MonitoringReview.candidate_id == c.id)).all()}
    for session in sessions:
        signals = db.scalars(select(MonitoringEvent).where(MonitoringEvent.session_id == session.id).order_by(MonitoringEvent.occurred_at)).all()
        review = reviews.get(session.round)
        monitoring.append({"round": session.round, "started_at": session.started_at.isoformat(), "deadline_at": session.deadline_at.isoformat(), "submitted_at": session.finished_at.isoformat() if session.finished_at else None, "warning_count": session.warning_count, "violation_limit": session.violation_limit, "submission_reason": session.submission_reason, "review": {"note": review.note, "reviewed_by": db.get(User, review.reviewed_by).name, "reviewed_at": review.reviewed_at.isoformat()} if review else None, "events": [{"kind": e.kind, "at": e.occurred_at.isoformat(), "duration_ms": e.duration_ms, "incident_id": e.incident_id} for e in signals]})
    return {"candidate": public_candidate(c, True), "attempts": [view_attempt(a, True) for a in attempts], "coding": [{"id": s.id, "submitted": s.submitted, "question_id": s.question_id, "language": s.language, "source": s.source, "status": s.status, "max_score": s.max_score, "score": s.score, "result": json.loads(s.result)} for s in codes], "coding_questions": [{k:v for k,v in q.items() if k not in ("tests", "test_cases")} for q in CODING], "interview": json.loads(interview.payload) if interview else None, "monitoring": monitoring, "history": [{"action": a.action, "at": a.created_at.isoformat()} for a in events]}


@app.put("/api/admin/candidates/{candidate_id}/monitoring/{round_name}/review")
def review_monitoring(candidate_id: int, round_name: str, body: MonitoringReviewIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    c = candidate_access(db, user, candidate_id, responsibilities=["technical_hr", "general_hr"])
    if round_name not in ("aptitude", "technical", "coding"): raise HTTPException(404, "Assessment round not found")
    if not assessment_session(db, c.id, round_name): raise HTTPException(404, "Assessment session not found")
    item = db.scalar(select(MonitoringReview).where(MonitoringReview.candidate_id == c.id, MonitoringReview.round == round_name))
    if not item:
        item = MonitoringReview(candidate_id=c.id, round=round_name, reviewed_by=user.id, note="")
        db.add(item)
    item.note = body.note; item.reviewed_by = user.id; item.reviewed_at = now()
    audit(db, user, c.id, "Reviewed " + round_name + " monitoring")
    db.commit()
    return {"saved": True}


@app.put("/api/admin/candidates/{candidate_id}/remarks/{round_name}")
def set_remarks(candidate_id: int, round_name: str, body: RemarksIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    roles = ["technical_team"] if round_name == "technical" else ["technical_hr", "general_hr"]
    c = candidate_access(db, user, candidate_id, responsibilities=roles)
    if round_name not in ("aptitude", "technical"): raise HTTPException(404, "Round not found")
    a = db.scalar(select(Attempt).where(Attempt.candidate_id == c.id, Attempt.round == round_name))
    if not a: raise HTTPException(404, "Assessment attempt not found")
    a.remarks = body.remarks[:5000]; audit(db, user, c.id, "Updated " + round_name + " remarks"); db.commit(); return {"saved": True}


@app.post("/api/admin/candidates/{candidate_id}/interview")
def submit_interview(candidate_id: int, body: InterviewIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    c = candidate_access(db, user, candidate_id, responsibilities=["technical_hr"])
    if body.recommendation not in ("Selected", "Reinterview", "Training recommended", "Not selected"): raise HTTPException(422, "Invalid recommendation")
    it = db.scalar(select(Interview).where(Interview.candidate_id == c.id))
    if not it: it = Interview(candidate_id=c.id, created_by=user.id, payload="{}"); db.add(it)
    it.payload = body.model_dump_json(); it.created_by = user.id; it.updated_at = now(); c.tech_recommendation = body.recommendation; c.stage = "General HR"
    audit(db, user, c.id, "Technical HR recommendation: " + body.recommendation); db.commit(); return {"saved": True}


@app.put("/api/admin/candidates/{candidate_id}/decision")
def decision(candidate_id: int, body: DecisionIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    c = candidate_access(db, user, candidate_id, responsibilities=["general_hr"])
    if body.decision not in ("Selected", "Reinterview", "Training recommended", "Not selected"): raise HTTPException(422, "Invalid decision")
    if body.channel and body.channel not in ("Email", "WhatsApp", "Phone", "In person"): raise HTTPException(422, "Invalid communication channel")
    c.final_decision = body.decision; c.communication_status = (body.channel + " recorded") if body.channel else "Ready to communicate"; c.stage = "Candidate Communication" if body.channel else "General HR"
    if body.released_result: c.released_result = body.released_result
    if body.release_feedback: c.release_feedback = body.release_feedback
    audit(db, user, c.id, "General HR decision: " + body.decision + ("; communication " + body.channel + " by " + body.communicator if body.channel else "")); db.commit(); return {"saved": True}


@app.post("/api/admin/candidates/{candidate_id}/communication")
def record_communication(candidate_id: int, body: CommunicateIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    c=candidate_access(db,user,candidate_id,responsibilities=["general_hr"])
    if body.channel not in ("Email", "WhatsApp", "Phone", "In person"): raise HTTPException(422,"Invalid communication channel")
    if not c.released_result: raise HTTPException(409,"Release the final result before recording communication")
    c.communication_status=body.channel+" "+body.status; c.stage="Candidate Communication"
    audit(db,user,c.id,"Candidate result communicated by "+(body.communicator or user.name)+" via "+body.channel); db.commit()
    return {"saved":True,"communication_status":c.communication_status}


@app.put("/api/admin/coding/{submission_id}/review")
def review_code(submission_id: int, body: CodeReviewIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    s = db.get(CodeSubmission, submission_id)
    if not s: raise HTTPException(404, "Submission not found")
    c = candidate_access(db, user, s.candidate_id, responsibilities=["technical_team"])
    db.refresh(c, with_for_update=True)
    db.refresh(s, with_for_update=True)
    if not s.submitted: raise HTTPException(409, "Candidate has not submitted this question")
    if body.score > s.max_score: raise HTTPException(422, "Score exceeds question maximum")
    reviewed_at = now()
    s.status = "Completed"; s.score = body.score; s.updated_at = reviewed_at
    s.result = json.dumps({"feedback": body.feedback, "reviewed_by": user.name, "reviewed_at": reviewed_at.isoformat()})
    reviewed = db.scalars(select(CodeSubmission).where(CodeSubmission.candidate_id == c.id).with_for_update()).all()
    if c.stage == "Coding" and len(reviewed) == 3 and all(item.submitted and item.status == "Completed" for item in reviewed):
        c.stage = "Technical HR"
    audit(db, user, c.id, f"Reviewed coding question {s.question_id}: {body.score}/{s.max_score}")
    db.commit()
    return {"saved": True, "status": s.status, "score": s.score, "stage": c.stage}


@app.get("/api/admin/report.csv")
def export_csv(request: Request, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    
    rows = dashboard(user, db)["candidates"]
    import csv, io
    output = io.StringIO(); w = csv.writer(output); w.writerow(["Candidate ID", "Name", "Email", "Role", "Stage", "Technical recommendation", "Final decision", "Communication"])
    for c in rows: w.writerow([c["id"], c["name"], c["email"], c["role"], c["stage"], c["tech_recommendation"], c["final_decision"], c["communication_status"]])
    audit(db, user, None, "Exported candidate CSV"); db.commit()
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=inetz-candidates.csv"})


@app.get("/api/admin/config")
def get_config(user=Depends(current_user)):
    require(user, ["admin"])
    return {"pass_marks": app.state.config["pass_marks"], "violation_limit": app.state.config["violation_limit"], "assessment_minutes": app.state.config["assessment_minutes"]}


@app.put("/api/admin/config")
def set_config(body: ConfigIn, user=Depends(current_user)):
    require(user, ["admin"])
    if set(body.pass_marks) != {"aptitude", "technical", "coding"} or any(not 0 <= x <= (100 if k == "coding" else 20 if k == "technical" else 15) for k, x in body.pass_marks.items()): raise HTTPException(422, "Invalid pass marks")
    app.state.config.update({"pass_marks": body.pass_marks, "violation_limit": body.violation_limit, "assessment_minutes": body.assessment_minutes})
    with DB() as db:
        setting=db.get(AppSetting, "pass_marks")
        if not setting: setting=AppSetting(key="pass_marks", value=json.dumps(body.pass_marks)); db.add(setting)
        else: setting.value=json.dumps(body.pass_marks)
        for key in ("violation_limit", "assessment_minutes"):
            setting = db.get(AppSetting, key)
            if not setting: db.add(AppSetting(key=key, value=str(getattr(body, key))))
            else: setting.value = str(getattr(body, key))
        db.commit()
    return {"saved": True, "pass_marks": body.pass_marks, "violation_limit": body.violation_limit, "assessment_minutes": body.assessment_minutes}


@app.get("/api/admin/staff")
def staff_list(user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "responsibilities": json.loads(u.responsibilities or "[]"), "active": u.active} for u in db.scalars(select(User).where(User.role == "admin")).all()]


@app.post("/api/admin/staff")
def add_staff(body: StaffIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    if len(body.password) < 10: raise HTTPException(422, "Password must be at least 10 characters")
    if db.scalar(select(User).where(User.email == body.email.lower())): raise HTTPException(409, "Email already exists")
    allowed = {"technical_team", "technical_hr", "general_hr", "all_candidates"}
    if set(body.responsibilities) - allowed: raise HTTPException(422, "Invalid responsibility")
    salt = secrets.token_hex(16); u = User(email=body.email.lower(), name=body.name, role="admin", responsibilities=json.dumps(body.responsibilities), salt=salt, password_hash=digest(body.password, salt)); db.add(u); db.commit(); return {"id": u.id}


@app.post("/api/admin/staff/{staff_id}/approve")
def approve_staff(staff_id: int, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    staff = db.get(User, staff_id)
    if not staff or staff.role != "admin": raise HTTPException(404, "Admin account not found")
    staff.active = True
    db.commit()
    return {"approved": True}


@app.put("/api/admin/staff/{staff_id}")
def edit_staff(staff_id: int, body: StaffIn, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    if body.password and len(body.password) < 10: raise HTTPException(422, "Password must be at least 10 characters")
    u = db.get(User, staff_id)
    if not u or u.role != "admin": raise HTTPException(404, "Admin account not found")
    if body.email.lower() != u.email and db.scalar(select(User).where(User.email == body.email.lower())): raise HTTPException(409, "Email already exists")
    if set(body.responsibilities) - {"technical_team", "technical_hr", "general_hr", "all_candidates"}: raise HTTPException(422, "Invalid responsibility")
    u.name = body.name; u.email = body.email.lower(); u.responsibilities = json.dumps(body.responsibilities)
    if body.password:
        u.salt = secrets.token_hex(16); u.password_hash = digest(body.password, u.salt)
    db.commit(); return {"saved": True}


@app.get("/api/admin/audit")
def audit_log(user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ["admin"])
    return [{"actor": db.get(User, a.actor_id).email, "candidate_id": a.candidate_id, "action": a.action, "at": a.created_at.isoformat()} for a in db.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(500)).all()]


class AnalyticsQuery(BaseModel):
    source: str = Field(min_length=1, max_length=12000)


@app.get('/api/candidate/analytics/config')
def analytics_config(user=Depends(current_user)):
    require(user, ['candidate'])
    from inetz.analytics import powerbi_embed_url
    return {'mysql_configured': bool(os.getenv('ANALYTICS_DATABASE_URL')), 'powerbi_embed_url': powerbi_embed_url()}


@app.post('/api/candidate/analytics/query')
def analytics_query(body: AnalyticsQuery, user=Depends(current_user), db: Session = Depends(db_session)):
    require(user, ['candidate'])
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    session = assessment_session(db, c.id, 'coding')
    if session and (session.finished_at or session.open_incident or utc(session.deadline_at) <= now()):
        raise HTTPException(409, 'The coding round is paused, finished, or expired.')
    from inetz.analytics import run_query
    return run_query(body.source)


@app.get("/{path:path}", response_class=HTMLResponse)
def frontend(path: str):
    file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(file, encoding="utf-8") as f: return f.read()
