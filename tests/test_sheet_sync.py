from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from inetz.models import AssessmentHistory, Attempt, Base, Candidate
from inetz.sheet_sync import HEADERS, SheetClient, candidate_cycles, sync_candidate, sync_candidate_safely


def test_sheet_sync_matches_headers_and_updates_existing_attempt():
    candidate = SimpleNamespace(id=4, full_name="=Candidate", mobile="9876543210",
                                degree="B.Tech", stream="Computer Science", role="Data Analyst",
                                candidate_status="Fresher")
    client = SheetClient.__new__(SheetClient)
    calls = []
    rows = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "?fields=sheets.properties.title":
            return {"sheets": [{"properties": {"title": "Candidates"}}]}
        if path.endswith("1:1"):
            return {"values": [["Unused", *HEADERS]]}
        if path.endswith("A2:AZ"):
            return {"values": [row.copy() for row in rows]}
        if path.endswith(":append"):
            rows.extend(kwargs["json"]["values"])
            return {}
        if path == "/values:batchUpdate":
            for item in kwargs["json"]["data"]:
                column = item["range"].split("!")[1].rstrip("0123456789")
                index = ord(column) - ord("A")
                rows[0][index] = item["values"][0][0]
            return {}
        raise AssertionError(path)

    client.request = request
    client.sync(candidate, [{}])
    assert rows[0] == ["", "=Candidate", "9876543210", "B.Tech", "Computer Science",
                       "Data Analyst", "Fresher", "", "", 1]
    client.sync(candidate, [{"aptitude": 12, "technical": 17}])
    assert len(rows) == 1
    assert rows[0][7:9] == [12, 17]
    writes = [call for call in calls if call[0] == "POST"]
    assert writes[0][2]["params"]["valueInputOption"] == "RAW"
    assert writes[1][2]["json"]["valueInputOption"] == "RAW"


def test_candidate_cycles_include_archived_and_current_scores():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        candidate = Candidate(full_name="Person", email="p@example.com", mobile="1234567890", role="Data Analyst")
        db.add(candidate)
        db.flush()
        for round_name, score in (("aptitude", 11), ("technical", 16)):
            db.add(AssessmentHistory(candidate_id=candidate.id, round=round_name, score=score,
                                     submitted_at=candidate.created_at, details="{}"))
        db.add(Attempt(candidate_id=candidate.id, round="aptitude", score=13,
                       submitted_at=candidate.created_at, snapshot="[]"))
        db.commit()
        cycles = candidate_cycles(db, candidate)
        assert cycles == [{"aptitude": 11, "technical": 16}, {"aptitude": 13}]
        fake = SimpleNamespace(sync=lambda c, value: value == cycles)
        assert sync_candidate(db, candidate.id, fake)
    engine.dispose()


def test_missing_sheet_credentials_are_reported_without_blocking_local_save(monkeypatch, caplog):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    assert sync_candidate_safely(None, 42) is False
    assert "Google Sheets sync skipped" in caplog.text
