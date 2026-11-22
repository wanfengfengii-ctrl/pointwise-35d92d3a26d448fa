from dataclasses import asdict, dataclass
import json

from station.capture.provenance import ReadingProvenance
from station.database import IntegrityViolation


@dataclass(frozen=True)
class SealedReport:
    report_id: str
    request_id: str
    attempt_id: int
    shift_id: str
    ticket_id: str
    revision_id: str
    original_id: int
    value_ug_l: int
    provenance: ReadingProvenance


def ensure_report_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE REFERENCES publication_requests(request_id),
            attempt_id INTEGER NOT NULL UNIQUE REFERENCES publication_attempts(attempt_id),
            shift_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            original_id INTEGER NOT NULL UNIQUE,
            value_ug_l TEXT NOT NULL,
            provenance TEXT NOT NULL,
            UNIQUE (shift_id, ticket_id)
        )
    ''')


def build_sealed_report(claim, revision_id, original):
    if (claim.shift_id, claim.original_id) != (original.shift_id, original.original_id):
        raise IntegrityViolation('report original differs from the formal seal claim')
    return SealedReport(
        f'report:{claim.request_id}', claim.request_id, claim.attempt_id, claim.shift_id,
        claim.ticket_id, revision_id, original.original_id, original.value_ug_l,
        original.provenance,
    )


def insert_report(conn, report):
    conn.execute('INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', (
        report.report_id, report.request_id, report.attempt_id, report.shift_id,
        report.ticket_id, report.revision_id, report.original_id, str(report.value_ug_l),
        json.dumps(asdict(report.provenance), ensure_ascii=False),
    ))


def load_report(conn, report_id):
    row = conn.execute('SELECT * FROM reports WHERE report_id = ?', (report_id,)).fetchone()
    if row is None:
        return None
    fields = dict(row)
    fields['value_ug_l'] = int(fields['value_ug_l'])
    fields['provenance'] = ReadingProvenance(**json.loads(fields['provenance']))
    return SealedReport(**fields)
