import hashlib
import json
import re
import secrets
from pathlib import Path
from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now(): return datetime.now(timezone.utc)
def utc(value): return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
def digest(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 310_000).hex()


class Base(DeclarativeBase): pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(24), default="candidate")
    salt: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254), index=True)
    mobile: Mapped[str] = mapped_column(String(32), default="")
    degree: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stream: Mapped[str | None] = mapped_column(String(100), nullable=True)
    candidate_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    area_of_interest: Mapped[str | None] = mapped_column(String(160), nullable=True)
    role: Mapped[str] = mapped_column(String(100), default="Full Stack")
    stage: Mapped[str] = mapped_column(String(48), default="Aptitude MCQ")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    round: Mapped[str] = mapped_column(String(24))
    snapshot: Mapped[str] = mapped_column(Text)
    answers: Mapped[str] = mapped_column(Text, default="{}")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pass_mark: Mapped[int] = mapped_column(Integer, default=8)
    __table_args__ = (UniqueConstraint("candidate_id", "round"),)


class AssessmentSession(Base):
    __tablename__ = "assessment_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    round: Mapped[str] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    violation_limit: Mapped[int] = mapped_column(Integer, default=3)
    open_incident: Mapped[str] = mapped_column(String(36), default="")
    open_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_reason: Mapped[str] = mapped_column(String(120), default="")
    __table_args__ = (UniqueConstraint("candidate_id", "round"),)


class AssessmentHistory(Base):
    __tablename__ = "assessment_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    round: Mapped[str] = mapped_column(String(24))
    score: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[str] = mapped_column(Text)


class QuestionPoolLock(Base):
    __tablename__ = "question_pool_lock"
    id: Mapped[int] = mapped_column(primary_key=True)


class MonitoringEvent(Base):
    __tablename__ = "monitoring_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("assessment_sessions.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(64), unique=True)
    incident_id: Mapped[str] = mapped_column(String(36), default="")
    kind: Mapped[str] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)



APTITUDE = [
    ("If 5 machines make 5 parts in 5 minutes, how long for 100 machines to make 100 parts?", ["5 minutes", "20 minutes", "100 minutes", "1 minute"], 0),
    ("What is 18% of 250?", ["35", "40", "45", "50"], 2),
    ("Find the next number: 2, 6, 12, 20, 30, ?", ["36", "40", "42", "44"], 2),
    ("A train covers 120 km in 2 hours. Its average speed is:", ["40 km/h", "50 km/h", "60 km/h", "80 km/h"], 2),
    ("If all Bloops are Razzies and all Razzies are Lazzies, all Bloops are:", ["Lazzies", "Not Lazzies", "Some Razzies", "Unknown"], 0),
    ("A product costing â‚¹800 is discounted by 15%. Sale price?", ["â‚¹660", "â‚¹680", "â‚¹700", "â‚¹720"], 1),
    ("The ratio of 24 to 36 in simplest form is:", ["2:3", "3:2", "4:5", "6:9"], 0),
    ("A can finish a job in 6 days and B in 3. Together they take:", ["1 day", "2 days", "3 days", "4 days"], 1),
    ("What is the median of 3, 9, 2, 8, 5?", ["3", "5", "5.4", "8"], 1),
    ("A number increased by 20% becomes 72. Original number?", ["58", "60", "62", "64"], 1),
    ("Which is the odd one out?", ["Square", "Triangle", "Circle", "Cube"], 3),
    ("A meeting starts at 10:35 and lasts 1 hour 45 minutes. It ends at:", ["12:10", "12:20", "12:30", "12:45"], 1),
    ("If x + 7 = 19, what is 3x?", ["24", "30", "36", "42"], 2),
    ("A bag has 3 red and 2 blue balls. Probability of red?", ["2/5", "3/5", "1/2", "3/2"], 1),
    ("Which fraction is largest?", ["3/5", "5/8", "2/3", "7/12"], 2),
]
TECH = [
    ("Which structure gives average O(1) key lookup?", ["Array scan", "Hash map", "Linked list", "Stack"], 1),
    ("Which SQL clause filters groups after aggregation?", ["WHERE", "ORDER BY", "HAVING", "LIMIT"], 2),
    ("What does HTTP status 201 indicate?", ["Created", "No content", "Forbidden", "Redirect"], 0),
    ("Which ACID property means a transaction is all-or-nothing?", ["Consistency", "Isolation", "Durability", "Atomicity"], 3),
    ("In Python, which type is immutable?", ["list", "dict", "set", "tuple"], 3),
    ("Which JavaScript method creates a new array by transforming each item?", ["filter", "map", "reduce", "sort"], 1),
    ("Which React hook manages local component state?", ["useMemo", "useState", "useRef", "useEffect"], 1),
    ("A database index primarily improves:", ["Read lookup speed", "Disk capacity", "Write speed always", "Normalization"], 0),
    ("Which is a valid REST practice for replacing a resource?", ["GET", "POST", "PUT", "TRACE"], 2),
    ("What does a foreign key enforce?", ["Referential integrity", "Encryption", "Sorting", "Compression"], 0),
    ("What is the time complexity of binary search on sorted data?", ["O(n)", "O(log n)", "O(n log n)", "O(1)"], 1),
    ("Which Java keyword prevents method overriding?", ["static", "private", "final", "const"], 2),
    ("Which CSS layout is designed for one-dimensional layouts?", ["Grid", "Flexbox", "Float", "Table"], 1),
    ("A SQL LEFT JOIN returns:", ["Only matching rows", "All right rows", "All left rows and matches", "Cartesian product"], 2),
    ("Which status code means the client is unauthenticated?", ["401", "403", "404", "500"], 0),
]


APTITUDE_BANK = json.loads(Path(__file__).with_name("aptitude_bank.json").read_text(encoding="utf-8"))
APTITUDE_BANK = {category: list({(q["question"], tuple(q["options"])): q for q in items}.values()) for category, items in APTITUDE_BANK.items()}
TECHNICAL_BANKS = json.loads(Path(__file__).with_name("technical_banks.json").read_text(encoding="utf-8"))


def technical_domain(role):
    normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", (role or "").casefold()).split())
    if "data analyst" in normalized or "data analytics" in normalized or "data analysis" in normalized:
        return "data_analyst"
    if "data science" in normalized or "data scientist" in normalized:
        return "data_science_ai_ml"
    if "ai ml" in normalized or "machine learning" in normalized:
        return "ai_ml_engineer"
    if "python" in normalized and "stack" in normalized:
        return "python_full_stack"
    if "java" in normalized and "stack" in normalized:
        return "java_full_stack"
    if "mern" in normalized or ("react" in normalized and "node" in normalized):
        return "mern_stack"
    return None


def pick_questions(pool, count, candidate_seen, global_seen):
    unique = {item["question"]: item for item in pool}.values()
    available = [item for item in unique if item["question"] not in candidate_seen and item["question"] not in global_seen]
    if len(available) < count:
        raise ValueError("Not enough unused questions remain in the shared question bank")
    return secrets.SystemRandom().sample(available, count)


def display_question(question):
    return re.sub(r"^Scenario\s+\d+\s*:\s*", "", question, count=1, flags=re.IGNORECASE)


def mcq_snapshot(round_name, role="", candidate_seen=None, global_seen=None):
    candidate_seen = candidate_seen or set()
    global_seen = global_seen or set()
    if round_name == "aptitude":
        rng = secrets.SystemRandom()
        chosen = [("Logical", q) for q in pick_questions(APTITUDE_BANK["logical"], 8, candidate_seen, global_seen)]
        chosen += [("Quantitative", q) for q in pick_questions(APTITUDE_BANK["quantitative"], 7, candidate_seen, global_seen)]
        rng.shuffle(chosen)
        return [{"id": i + 1, "category": category, "source_id": q["id"], "question": display_question(q["question"]), "options": q["options"], "answer": q["answer"]} for i, (category, q) in enumerate(chosen)]
    domain = technical_domain(role)
    pool = TECHNICAL_BANKS.get(domain) if domain else None
    if pool:
        chosen = pick_questions(pool, 20, candidate_seen, global_seen)
        return [{"id": i + 1, "source_id": q["id"], "domain": domain, "category": q["category"], "question": display_question(q["question"]), "options": q["options"], "answer": q["answer"]} for i, q in enumerate(chosen)]
    generic = TECH + [
        ("Which HTTP method is normally used to retrieve data?", ["POST", "GET", "PATCH", "DELETE"], 1),
        ("What does a primary key identify?", ["A unique row", "A database server", "A CSS class", "A network route"], 0),
        ("Which structure follows last-in, first-out order?", ["Queue", "Tree", "Stack", "Graph"], 2),
        ("Which SQL command adds a new row?", ["INSERT", "ALTER", "DROP", "GRANT"], 0),
        ("What does JSON represent?", ["A data interchange format", "A database engine", "A programming language", "A web server"], 0),
    ]
    chosen = pick_questions([{"question": q, "options": opts, "answer": answer} for q, opts, answer in generic], 20, candidate_seen, global_seen)
    return [{"id": i + 1, **item} for i, item in enumerate(chosen)]


class Login(BaseModel): email: EmailStr; password: str
class CandidateSignup(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    mobile: str = Field(min_length=7, max_length=24)
    degree: str = Field(min_length=2, max_length=100)
    stream: str = Field(min_length=2, max_length=100)
    candidate_status: str = Field(pattern="^(Fresher|Experienced|Career gap|Student)$")

    @field_validator("name", "degree", "stream", "role")
    @classmethod
    def nonblank_detail(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Enter at least 2 characters")
        return value.strip()
    role: str = Field(default="Full Stack", min_length=2, max_length=100)

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value):
        value = value.strip()
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"\+?[0-9\s().-]+", value) or not 7 <= len(digits) <= 15:
            raise ValueError("Enter a valid phone number with 7 to 15 digits")
        return value
class SaveAnswers(BaseModel): answers: dict[str, int]
class StartAssessment(BaseModel): acknowledged: bool
class MonitorIn(BaseModel): kind: str; event_key: str = Field(min_length=8, max_length=64); answers: dict[str, int] | None = None





