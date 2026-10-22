# iNetz Candidate Assessments

A FastAPI candidate portal for aptitude and domain-specific technical MCQ assessments. It stores candidate accounts and profiles, question snapshots and answers, scores, assessment duration, and browser monitoring events.

## Run locally

Install Python 3.12+ and MySQL 8. Create a MySQL database and a least-privilege application user, then set `DATABASE_URL` in `.env`. Start from the sample configuration:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Set a private `SESSION_SECRET` with at least 32 random characters. Candidates create their own accounts at `/candidate/register` and sign in at `/candidate`.

## Assessments and records

- Aptitude: 15 questions, 30 minutes.
- Technical MCQ: 20 role-specific questions, 20 minutes.
- Answers save to the database; saved answers are scored when submitted or when the timer expires.
- Browser warnings, event details, warning counts, and time extensions are recorded with the assessment session.
- Candidate scores and their own profile are available in the candidate portal. The app has no Admin portal or candidate assignment workflow.

The application uses these MySQL tables: `users`, `candidates`, `attempts`, `assessment_sessions`, and `monitoring_events`.
