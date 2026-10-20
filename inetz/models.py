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
    responsibilities: Mapped[str] = mapped_column(Text, default="[]")
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
    role: Mapped[str] = mapped_column(String(100), default="Full Stack")
    assigned_admin: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    stage: Mapped[str] = mapped_column(String(48), default="Aptitude MCQ")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    final_decision: Mapped[str] = mapped_column(String(40), default="Awaiting decision")
    tech_recommendation: Mapped[str] = mapped_column(String(40), default="Awaiting interview")
    communication_status: Mapped[str] = mapped_column(String(40), default="Not communicated")
    released_result: Mapped[str] = mapped_column(String(40), default="")
    release_feedback: Mapped[str] = mapped_column(Text, default="")


class Attempt(Base):
    __tablename__ = "attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    round: Mapped[str] = mapped_column(String(24))
    snapshot: Mapped[str] = mapped_column(Text)
    answers: Mapped[str] = mapped_column(Text, default="{}")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
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


class MonitoringEvent(Base):
    __tablename__ = "monitoring_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("assessment_sessions.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(64), unique=True)
    incident_id: Mapped[str] = mapped_column(String(36), default="")
    kind: Mapped[str] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MonitoringReview(Base):
    __tablename__ = "monitoring_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    round: Mapped[str] = mapped_column(String(24))
    note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("candidate_id", "round"),)


class CodeSubmission(Base):
    __tablename__ = "code_submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    question_id: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(Text)
    submitted: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="Not submitted")
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_score: Mapped[int] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(Text, default="{}")
    judge_token: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("candidate_id", "question_id"),)


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), unique=True)
    payload: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Invitation(Base):
    __tablename__ = "candidate_invitations"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Audit(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("candidates.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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


def mcq_snapshot(round_name, role=""):
    if round_name == "aptitude":
        rng = secrets.SystemRandom()
        chosen = [("Logical", q) for q in rng.sample(APTITUDE_BANK["logical"], 8)]
        chosen += [("Quantitative", q) for q in rng.sample(APTITUDE_BANK["quantitative"], 7)]
        rng.shuffle(chosen)
        return [{"id": i + 1, "category": category, "source_id": q["id"], "question": q["question"], "options": q["options"], "answer": q["answer"]} for i, (category, q) in enumerate(chosen)]
    domain = technical_domain(role)
    pool = TECHNICAL_BANKS.get(domain) if domain else None
    if pool:
        chosen = secrets.SystemRandom().sample(pool, 20)
        return [{"id": i + 1, "source_id": q["id"], "domain": domain, "category": q["category"], "question": q["question"], "options": q["options"], "answer": q["answer"]} for i, q in enumerate(chosen)]
    generic = TECH + [
        ("Which HTTP method is normally used to retrieve data?", ["POST", "GET", "PATCH", "DELETE"], 1),
        ("What does a primary key identify?", ["A unique row", "A database server", "A CSS class", "A network route"], 0),
        ("Which structure follows last-in, first-out order?", ["Queue", "Tree", "Stack", "Graph"], 2),
        ("Which SQL command adds a new row?", ["INSERT", "ALTER", "DROP", "GRANT"], 0),
        ("What does JSON represent?", ["A data interchange format", "A database engine", "A programming language", "A web server"], 0),
    ]
    return [{"id": i + 1, "question": q, "options": opts, "answer": answer} for i, (q, opts, answer) in enumerate(generic)]


CODING = [
    {"id": 1, "title": "Two Sum", "difficulty": "Intermediate", "marks": 20, "statement": "Find the positions of two numbers in the list that add up to the target. Return the two positions as a list. Positions start at 0. There is exactly one correct pair, and you cannot use the same list item twice.", "constraints": "The list has 2 to 100,000 numbers. Each number and the target are between -1,000,000,000 and 1,000,000,000. Aim for a solution that checks the list once.", "examples": [{"input": "nums = [2, 7, 11, 15], target = 9", "output": "[0, 1]", "explanation": "nums[0] is 2 and nums[1] is 7. 2 + 7 = 9, so return their positions: [0, 1]."}], "tests": [[[2, 7, 11, 15], 9, [0, 1]], [[3, 2, 4], 6, [1, 2]], [[3, 3], 6, [0, 1]]]},
    {"id": 2, "title": "Longest Unique Substring", "difficulty": "Advanced", "marks": 40, "statement": "Find the length of the longest piece of the text that has no repeated characters. The piece must be continuous: characters next to each other in the original text.", "constraints": "The text can be empty or contain up to 50,000 letters, numbers, spaces, or symbols.", "examples": [{"input": 's = "abcabcbb"', "output": "3", "explanation": "The piece \"abc\" has no repeated characters and has length 3. Longer pieces repeat a character."}], "tests": [["abcabcbb", 3], ["bbbbb", 1], ["pwwkew", 3], ["", 0]]},
    {"id": 3, "title": "Merge Overlapping Intervals", "difficulty": "Advanced", "marks": 40, "statement": "You are given ranges written as [start, end]. Combine ranges that overlap, then return the combined ranges in order from smallest start to largest start.", "constraints": "There are 1 to 100,000 ranges. Each range has a start and end between 0 and 10,000. A range's start is never greater than its end.", "examples": [{"input": "[[1, 3], [2, 6], [8, 10]]", "output": "[[1, 6], [8, 10]]", "explanation": "[1, 3] and [2, 6] overlap, so combine them into [1, 6]. [8, 10] does not overlap, so keep it separate."}], "tests": [[[[1, 3], [2, 6], [8, 10], [15, 18]], [[1, 6], [8, 10], [15, 18]]], [[[1, 4], [4, 5]], [[1, 5]]], [[[1, 4]], [[1, 4]]]]},
]


def starter(qid, language):
    if language == "python":
        fn = ["def solution(nums, target):\n    pass", "def solution(s):\n    pass", "def solution(intervals):\n    pass"][qid - 1]
        return fn + "\n\nif __name__ == '__main__':\n    import json, sys\n    data=json.load(sys.stdin)\n    print(json.dumps(solution(*data) if isinstance(data,list) else solution(data)))"
    if language == "javascript":
        fn = ["function solution(nums, target) {\n  // your code\n}", "function solution(s) {\n  // your code\n}", "function solution(intervals) {\n  // your code\n}"][qid - 1]
        return fn + "\nconst data=JSON.parse(require('fs').readFileSync(0,'utf8')); console.log(JSON.stringify(Array.isArray(data)&&Array.isArray(data[0]) ? solution(...data) : solution(data)));"
    fn = ["static int[] solution(int[] nums, int target) { return new int[0]; }", "static int solution(String s) { return 0; }", "static int[][] solution(int[][] intervals) { return intervals; }"][qid - 1]
    return "import java.util.*;\npublic class Main {\n  " + fn + "\n  public static void main(String[] args) { /* read JSON input and print JSON result */ }\n}"


class Login(BaseModel): email: EmailStr; password: str
class Register(BaseModel): name: str = Field(min_length=2, max_length=160); email: EmailStr; password: str = Field(min_length=10); mobile: str = ""; role: str = "Full Stack"
class CandidateSignup(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=8, max_length=8)
    mobile: str = Field(min_length=7, max_length=24)
    role: str = Field(default="Full Stack", min_length=2, max_length=100)

    @field_validator("mobile")
    @classmethod
    def validate_mobile(cls, value):
        value = value.strip()
        digits = re.sub(r"\D", "", value)
        if not re.fullmatch(r"\+?[0-9\s().-]+", value) or not 7 <= len(digits) <= 15:
            raise ValueError("Enter a valid phone number with 7 to 15 digits")
        return value
class AdminSignup(BaseModel): name: str = Field(min_length=2, max_length=160); email: EmailStr; password: str = Field(min_length=10)
class Redeem(BaseModel): token: str = Field(min_length=20, max_length=200); password: str = Field(min_length=8, max_length=8)
class CandidateIn(BaseModel): name: str = Field(min_length=2, max_length=160); email: EmailStr; mobile: str = ""; role: str = "Full Stack"; admin_id: int | None = None
class AssignIn(BaseModel): admin_id: int | None = None
class SaveAnswers(BaseModel): answers: dict[str, int]
class StartAssessment(BaseModel): acknowledged: bool
class MonitorIn(BaseModel): kind: str; event_key: str = Field(min_length=8, max_length=64); answers: dict[str, int] | None = None; question_id: int | None = None; language: str | None = None; source: str | None = None
class CodeIn(BaseModel): question_id: int; language: str; source: str
class CodeReviewIn(BaseModel): score: int = Field(ge=0); feedback: str = Field(min_length=1, max_length=5000)
class InterviewIn(BaseModel): interview_date: str = ""; interviewer: str = ""; questions: str = ""; responses: str = ""; strengths: str = ""; gaps: str = ""; communication: str = ""; remarks: str = ""; next_steps: str = ""; recommendation: str
class DecisionIn(BaseModel): decision: str; remarks: str = ""; next_steps: str = ""; released_result: str = ""; release_feedback: str = ""; channel: str = ""; communicator: str = ""
class RemarksIn(BaseModel): remarks: str
class MonitoringReviewIn(BaseModel): note: str = Field(max_length=5000)
class CommunicateIn(BaseModel): channel: str; communicator: str = ""; status: str = "Sent"
class StaffIn(BaseModel): name: str; email: EmailStr; password: str = ""; responsibilities: list[str] = []
class ConfigIn(BaseModel): pass_marks: dict[str, int] = {"aptitude": 8, "technical": 8, "coding": 60}; violation_limit: int = Field(default=3, ge=0, le=20); assessment_minutes: int = Field(default=60, ge=5, le=240)





