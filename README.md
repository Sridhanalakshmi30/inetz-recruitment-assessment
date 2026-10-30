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

Candidates register and sign in with an email address and password. Registration does not verify ownership of the email address; configure an email verification service before relying on the address for sensitive messages or password recovery. Accounts previously created only through Google sign-in need a password reset before they can sign in.

## Deploy on Vercel

1. Push this repository to GitHub and import it into Vercel. Vercel detects the FastAPI app from `app.py` and uses the project `requirements.txt`.
2. Add these environment variables in the Vercel project settings for Production (and Preview if needed):
   - `DATABASE_URL`: a persistent MySQL URL using the `mysql+pymysql://` scheme. Do not use the local SQLite fallback on Vercel; serverless files are not persistent.
   - `SESSION_SECRET`: a private random value with at least 32 characters.
   - `COOKIE_SECURE`: `true`.
3. Deploy, then check `https://<your-project>.vercel.app/api/health` for `{"status":"ok","database":"connected"}`.

The app creates missing tables at startup. Use an external persistent MySQL database and keep `.env` and production credentials out of Git.

## Assessments and records

- Aptitude: 15 questions, 30 minutes.
- Technical MCQ: 20 role-specific questions, 20 minutes.
- Question selection does not reuse questions across candidates or later attempts. A new attempt is blocked when its role's bank has too few unused questions.
- Answers save to the database; saved answers are scored when submitted or when the timer expires.
- After both MCQ rounds are submitted, candidates can start a new Aptitude and Technical cycle 24 hours after their Technical submission. Previous results remain in assessment history.
- Browser warnings, event details, warning counts, and time extensions are recorded with the assessment session.
- Candidate scores and their own profile are available in the candidate portal. The app has no Admin portal or candidate assignment workflow.

The application uses these MySQL tables: `users`, `candidates`, `attempts`, `assessment_sessions`, `monitoring_events`, and `assessment_history`. Existing `coding_submissions` records are retained in the database.

## Google Sheet results

The app can mirror registrations and scores to the Google Sheet configured by `GOOGLE_SHEET_ID` (the supplied sheet ID is the default). It finds a tab containing these headers: `Name`, `Phone Number`, `Degree`, `Domain`, `Applied role`, `Current Status`, `Aptitude Mark`, `Technical MCQ`, and `Attempt of test`. `Domain` comes from the registration Stream/Domain field. Each daily test cycle has its own row; scores are filled after each MCQ submission. Other columns are left alone. Values are written as raw text/numbers so candidate entries cannot become spreadsheet formulas.

Create a Google Cloud service account with the Google Sheets API enabled, share the target sheet with its `client_email` as Editor, and set `GOOGLE_SERVICE_ACCOUNT_JSON` to the full service account JSON in the server environment. For local development, `GOOGLE_SERVICE_ACCOUNT_FILE` can point to the downloaded JSON file instead. Keep the key out of Git. If more than one tab has those headers, set `GOOGLE_SHEET_TAB` to the intended tab name.

After configuring access, run `python sync_sheet.py` to backfill existing candidates or retry a failed sync. Registrations and assessment submissions still save locally if Google Sheets is temporarily unavailable; the backfill command reconciles rows using name, phone number, and attempt number. Keep those three values unique per candidate in the sheet.
