# iNetz Recruitment Assessment — Project Knowledge

## What the application does

This is a FastAPI recruitment portal. Candidates create accounts, complete aptitude and role-specific technical MCQ assessments, and view their results in a candidate portal. Assessment scores and candidate profile details can be mirrored to a configured Google Sheet.

## Main parts of the codebase

- `app.py` — HTTP routes, authentication, assessment lifecycle, persistence, and application startup.
- `inetz/models.py` — SQLAlchemy database models, candidate validation, question selection, and assessment snapshots.
- `inetz/aptitude_bank.json` — logical and quantitative aptitude question banks.
- `inetz/technical_banks.json` — technical question banks by applied role/domain.
- `inetz/sheet_sync.py` — maps candidate profile and assessment-cycle data into Google Sheets columns.
- `sync_sheet.py` — backfills/retries candidate rows in the configured Google Sheet.
- `static/index.html` — shared application shell and page rendering.
- `static/candidate_signup.js`, `static/candidate_portal.js`, `static/candidate_portal.css` — candidate registration and portal UI.
- `tests/` — registration, assessment rotation/monitoring, answer evaluation, and sheet-sync tests.

## Local setup and run

Python 3.12+ is required. Install dependencies and start the app from the project root:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app:app --host 127.0.0.1 --port 8001
```

The app serves both frontend pages and API routes from the same server. Check server health at `http://127.0.0.1:8001/api/health`; the registration page is at `http://127.0.0.1:8001/candidate/register`.

Configure the database and a private `SESSION_SECRET` in `.env`. `DATABASE_URL` must be a valid SQLAlchemy URL, for example a MySQL URL using `mysql+pymysql://`. Save `.env` as UTF-8 without a byte-order mark so `python-dotenv` recognizes the first variable correctly. Never commit `.env` or service-account keys.

## Candidate registration and accounts

Registration collects name, email, password, phone, degree, stream/domain, current status, and applied role. Email addresses are normalized to lowercase. An email can have only one account. If it is already registered, the registration page directs the candidate to sign in; use a different email to create a new account.

The registration route stores candidate details in the database, then attempts to sync them to Google Sheets. It does not verify mailbox ownership. Candidate password authentication is handled by `/api/login`; sessions use the `inetz_session` HTTP-only cookie.

## Assessment behavior

- Aptitude: 15 questions (8 logical, 7 quantitative), 30-minute limit.
- Technical MCQ: 20 questions selected for the candidate's applied role, 20-minute limit.
- Each attempt stores its own question snapshot, answer choices, and answer keys. Scoring uses that saved snapshot, not the latest bank contents.
- Each correct answer earns one point. Incorrect and unanswered answers earn zero; negative marking is not enabled.
- Results show the score and pass benchmark. The pass benchmark does not prevent progression to the next round.
- Questions are selected without reuse from candidate history or prior shared attempts. A new attempt fails if the relevant unused pool cannot supply enough questions.
- After both rounds are completed, another daily cycle becomes available 24 hours after technical submission.

## Google Sheets integration

The default sheet ID is configured in `inetz/sheet_sync.py` and can be overridden with `GOOGLE_SHEET_ID`. The sync locates a tab containing these headers:

`Name`, `Phone Number`, `Degree`, `Domain`, `Applied role`, `Current Status`, `Aptitude Mark`, `Technical MCQ`, `Attempt of test`.

`Domain` is sourced from the candidate's saved `stream`. Candidate registration and assessment submission trigger sync attempts. Each assessment cycle gets a row; scores are filled when each round is submitted. Existing rows are reconciled using name, phone, and attempt number.

For authentication, create a Google Cloud service account, enable the Google Sheets API, share the spreadsheet with the service account email as Editor, and set one of these server environment variables:

```env
GOOGLE_SERVICE_ACCOUNT_FILE=C:\path\to\service-account-key.json
```

or `GOOGLE_SERVICE_ACCOUNT_JSON` with the full service-account JSON. Keep the key private. Optionally set `GOOGLE_SHEET_TAB` to choose a specific tab. After configuration, run `python sync_sheet.py` to backfill or retry rows. The local database remains the source of truth if a sheet write fails.

## Tests

Run the complete Python test suite without pytest's filesystem cache:

```powershell
python -m pytest tests -q -p no:cacheprovider
```

For candidate registration and sheet-sync changes, run:

```powershell
python -m pytest tests/test_registration.py tests/test_sheet_sync.py -q -p no:cacheprovider
```

## Troubleshooting

- **Google Sheet stays blank:** confirm the running backend loaded the current `.env`, the service-account JSON file exists, the Sheets API is enabled, and the spreadsheet is shared with the service account as Editor. Restart the backend after changing environment settings, then run `python sync_sheet.py`.
- **Duplicate email response:** this means an account with that email is already in the active database. Sign in with that email; a duplicate account is not created.
- **Registration details are missing for older candidates:** older database rows may not contain the newer profile fields. Sync cannot infer phone, degree, domain, or status that was never saved; update the candidate's source record before syncing again.
- **Database seems to have the wrong users:** check the effective `DATABASE_URL` and `.env` encoding. A malformed first variable can cause the app to use the local SQLite fallback instead of the configured database.
- **Question allocation fails:** the system does not reuse questions to satisfy an assessment. Add enough unique questions to the relevant role bank before allocating another attempt.
