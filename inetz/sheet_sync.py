"""Mirror candidate assessment cycles into the configured Google Sheet."""

import json
import logging
import os
from urllib.parse import quote

from sqlalchemy import select

from .models import AssessmentHistory, Attempt, Candidate

SHEET_ID = "1r_0BfBC5v0yECP17hC1E-mnNWYimZyhghO-O_or3oCA"
HEADERS = ("Name", "Phone Number", "Degree", "Domain", "Applied role",
           "Current Status", "Aptitude Mark", "Technical MCQ", "Attempt of test")
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
log = logging.getLogger(__name__)


def configured():
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE"))


def candidate_cycles(db, candidate):
    history = db.scalars(select(AssessmentHistory).where(
        AssessmentHistory.candidate_id == candidate.id).order_by(AssessmentHistory.id)).all()
    archived = []
    for item in history:
        if item.round == "aptitude" or not archived:
            archived.append({})
        archived[-1][item.round] = item.score
    current = {item.round: item.score for item in db.scalars(select(Attempt).where(
        Attempt.candidate_id == candidate.id, Attempt.submitted_at.is_not(None))).all()}
    return [*archived, current]


def row_values(candidate, cycle, scores):
    return [candidate.full_name, candidate.mobile, candidate.degree or "", candidate.stream or "",
            candidate.role, candidate.candidate_status or "", scores.get("aptitude", ""),
            scores.get("technical", ""), cycle]


class SheetClient:
    def __init__(self):
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession

        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if raw:
            credentials = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=[SCOPE])
        else:
            credentials = service_account.Credentials.from_service_account_file(
                os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"], scopes=[SCOPE])
        self.http = AuthorizedSession(credentials)
        self.base = f"https://sheets.googleapis.com/v4/spreadsheets/{os.getenv('GOOGLE_SHEET_ID', SHEET_ID)}"

    def request(self, method, path, **kwargs):
        response = self.http.request(method, self.base + path, timeout=10, **kwargs)
        response.raise_for_status()
        return response.json()

    def sheet_layout(self):
        titles = [sheet["properties"]["title"] for sheet in self.request(
            "GET", "?fields=sheets.properties.title")["sheets"]]
        preferred = os.getenv("GOOGLE_SHEET_TAB")
        if preferred:
            if preferred not in titles:
                raise ValueError(f"Google Sheet tab {preferred!r} does not exist")
            titles = [preferred]
        for title in titles:
            prefix = quote(f"'{title.replace(chr(39), chr(39) * 2)}'!", safe="")
            header = self.request("GET", f"/values/{prefix}1:1").get("values", [[]])[0]
            positions = {str(value).strip().casefold(): index for index, value in enumerate(header)}
            if all(name.casefold() in positions for name in HEADERS):
                return title, [positions[name.casefold()] for name in HEADERS]
        raise ValueError("No Google Sheet tab contains all nine expected column headers")

    def sync(self, candidate, cycles):
        title, positions = self.sheet_layout()
        a1_prefix = f"'{title.replace(chr(39), chr(39) * 2)}'!"
        quoted = quote(a1_prefix, safe="")
        sheet_rows = self.request("GET", f"/values/{quoted}A2:AZ").get("values", [])
        name_col, phone_col, *_, attempt_col = positions
        for cycle_number, scores in enumerate(cycles, 1):
            values = row_values(candidate, cycle_number, scores)
            matches = []
            for row_number, row in enumerate(sheet_rows, 2):
                cell = lambda col: str(row[col]).strip() if col < len(row) else ""
                if (cell(name_col), cell(phone_col), cell(attempt_col)) == (
                    candidate.full_name.strip(), candidate.mobile.strip(), str(cycle_number)):
                    matches.append(row_number)
            if len(matches) > 1:
                raise ValueError(f"Duplicate sheet rows for candidate {candidate.id}, attempt {cycle_number}")
            if matches:
                row_number = matches[0]
                data = [{"range": f"{a1_prefix}{column_name(col)}{row_number}", "values": [[value]]}
                        for col, value in zip(positions, values)]
                self.request("POST", "/values:batchUpdate", json={"valueInputOption": "RAW", "data": data})
            else:
                row = [""] * (max(positions) + 1)
                for col, value in zip(positions, values):
                    row[col] = value
                self.request("POST", f"/values/{quoted}A:AZ:append",
                             params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                             json={"values": [row]})
                sheet_rows.append(row)


def column_name(index):
    result = ""
    while index >= 0:
        index, remainder = divmod(index, 26)
        result = chr(65 + remainder) + result
        index -= 1
    return result


def sync_candidate(db, candidate_id, client=None):
    if client is None:
        if not configured():
            return False
        client = SheetClient()
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        return False
    client.sync(candidate, candidate_cycles(db, candidate))
    return True


def sync_candidate_safely(db, candidate_id):
    if not configured():
        log.warning("Google Sheets sync skipped for candidate %s: configure GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE", candidate_id)
        return False
    try:
        return sync_candidate(db, candidate_id)
    except Exception:
        log.exception("Google Sheet sync failed for candidate %s", candidate_id)
        return False
