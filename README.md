# iNetz Technologies Recruitment and Assessment

Python 3.12+, FastAPI, SQLAlchemy and MySQL 8. The responsive web interface is served by FastAPI; the application includes Candidate and Admin experiences, cookie sessions, server-side MCQ scoring, interview/HR records and manual coding review by Admins.

## Run locally

Install Python 3.12+ and MySQL 8. In a MySQL administrator session, create the application database and user (choose your own password):

```sql
CREATE DATABASE inetz_recruitment CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'inetz'@'127.0.0.1' IDENTIFIED BY 'replace-with-a-private-password';
GRANT ALL PRIVILEGES ON inetz_recruitment.* TO 'inetz'@'127.0.0.1';
```

Then, from this project directory in PowerShell:

```powershell
Copy-Item .env.example .env
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Before starting the app, edit `.env`: put the MySQL password in `DATABASE_URL`, choose a private `SESSION_SECRET` of at least 32 random characters, and set unique `ADMIN_EMAIL` and `ADMIN_PASSWORD` values. URL-encode special characters in the database password.

Open `http://127.0.0.1:8000`. The first startup creates the Admin specified in `.env`. Staff use `/admin` to sign in or `/admin/register` to request an Admin account. Requests stay disabled until an existing Admin approves them under **Team access**. Admins can also create Admin accounts directly there. Existing Super Admin accounts become Admin accounts at startup. Set `COOKIE_SECURE=true` when serving over HTTPS. Never commit `.env`; back up MySQL and restrict database network access. SQLAlchemy creates missing tables on startup; this version has no schema migration framework.

For a quick local development session, `DATABASE_URL=sqlite:///./inetz-dev.db` is supported. MySQL is the intended persistent database.

## Manual coding review

Candidates save and submit three coding answers. Submissions are locked and appear in **Admin portal -> Candidate report -> Coding submissions**. An Admin can inspect each source file, enter a score within that question's maximum (20, 40, or 40), and write feedback. The reviewer and review time are saved with the score and recorded in the audit log. When all three answers are reviewed, the candidate moves to Technical HR. Browser monitoring events remain separate from scores and recommendations. Candidate code is never executed by this application.

Existing submitted answers that were waiting for the former Judge0 connection are moved to **Awaiting review** at startup; their source remains saved.

## Candidate access

HR registration creates an application record and a single-use seven-day invitation URL. Share it securely with the candidate. The link opens `/setup-account?token=...`, binds their account to the registered candidate and creates their password. Candidates may also self-register at the sign-in page; their role is always Candidate. Candidate sessions cannot read internal remarks, answer keys, hidden test cases, source of another candidate, or unreleased decisions. An answer draft and code draft persist in MySQL.

## Workflow

Registration â†’ Aptitude (15 questions) â†’ Technical MCQ (15 questions) â†’ Coding (20/40/40) â†’ Technical HR â†’ General HR â†’ Candidate communication. MCQ and coding scores never automatically block progression or decide hiring. Pass marks are configurable by Admins and are snapshotted on an MCQ attempt. Technical HR recommendations and General HR decisions are separate fields; result feedback is released separately to the candidate.

## Focused assessment and monitoring

For each MCQ round and the coding round, the candidate acknowledges the rules and enters fullscreen before the round starts. The app hides portal navigation while the round is active. It autosaves MCQ answers and coding drafts in the database, with a browser-local draft retained until a server save succeeds. The browser displays an unsaved-work warning where supported. The server snapshots the assessment deadline and permitted warning count when the round starts, rejects edits after submission, and handles repeated final-submission requests without duplicating scores.

The client reports page-hidden, focus-loss and fullscreen-exit signals. Overlapping signals form one incident and add one warning. When the candidate leaves fullscreen or focus, answer controls lock and the server pauses the assessment deadline until the candidate returns. A return signal records the measured incident duration. Admins can set the warning reference count (0â€“20) and duration (5â€“240 minutes) under **Assessment settings**. Warnings are recorded for authorized staff review; they do not submit or score an assessment. All monitoring events, warning counts, saved MCQ answers, and submission reasons appear in the authorized candidate report. Monitoring never changes a hiring recommendation or final decision.

During an active assessment, the browser blocks paste and external text drops in response controls and the code editor. It records a blocked attempt without sending clipboard contents. It also limits copying, cutting, text selection and context menus within question content. Browser controls cannot prevent use of another tab, application or device, and cannot prevent screenshots, photography or browser-tool extraction. HR should review the circumstances behind each flag.

Assessment rounds use browser fullscreen and focus monitoring. These signals are recorded for staff review.

## Roles and API security

- Candidate endpoints require a Candidate role and resolve only the candidate linked to that session.
- Admin endpoints require the Admin role. Admins can manage candidates, other Admin accounts, assessment settings and audit records. Server secrets are never returned.
- CSV export requires an Admin account.
- Sensitive user actions are written to the audit log.

The app uses HTTP-only, SameSite=Lax cookies and PBKDF2 password hashing. Place it behind HTTPS, set `COOKIE_SECURE=true`, rotate credentials, add a reverse proxy rate limit for authentication, and monitor the service and database in production. Use `/api/health` as a readiness check.

## Current scope and production notes

The supplied version implements the core workflow, database records, role checks, candidate invitation, CSV export and responsive screens. Assessment banks, request schemas and database models are defined in `inetz/models.py`; database setup is in `inetz/database.py`. API routes remain registered in `app.py`. An attempt stores a question snapshot, though the current question bank has no editor/version browser yet. PDF export, email/WhatsApp delivery integrations, MySQL migration scripts, and a comprehensive automated acceptance test suite still need implementation before claiming every pasted acceptance criterion is production-complete.

## Development access

The first-run Admin is created from `ADMIN_EMAIL` / `ADMIN_PASSWORD`; configure unique local-only credentials. Admins can create or approve other Admins. Candidate access is created using invitations or candidate self-registration. There are no baked-in demo credentials.

