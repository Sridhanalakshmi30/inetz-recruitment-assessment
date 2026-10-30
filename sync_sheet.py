"""Backfill or retry all candidate rows in the configured Google Sheet."""

from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()
import app as system
from inetz.database import DB
from inetz.models import Candidate
from inetz.sheet_sync import SheetClient, configured, sync_candidate


def main():
    if not configured():
        raise SystemExit("Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE first")
    system.startup()
    client = SheetClient()
    with DB() as db:
        ids = db.scalars(select(Candidate.id).order_by(Candidate.id)).all()
        failed = []
        for candidate_id in ids:
            try:
                sync_candidate(db, candidate_id, client)
            except Exception as error:
                failed.append(candidate_id)
                print(f"Candidate {candidate_id}: {error}")
    print(f"Synced {len(ids) - len(failed)} of {len(ids)} candidates")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
