from dataclasses import dataclass

from station.archive.receipts import FirstReceipt, load_first_receipt
from station.archive.reports import SealedReport, load_report
from station.database import IntegrityViolation, InvalidInput, require_name


@dataclass(frozen=True)
class ReportPublication:
    report: SealedReport
    receipt: FirstReceipt


@dataclass(frozen=True)
class PublicationOutcome:
    attempt_id: int
    request_id: str
    shift_id: str
    ticket_id: str
    state: str
    original_id: int | None
    publication: ReportPublication | None


def _load_pair(conn, report_id):
    report = load_report(conn, report_id)
    if report is None:
        return None
    receipt = load_first_receipt(conn, report_id)
    if receipt is None or receipt.request_id != report.request_id:
        raise IntegrityViolation('the frozen report does not have its matching first receipt')
    return ReportPublication(report, receipt)


def read_report(store, *, report_id=None, request_id=None):
    if (report_id is None) == (request_id is None):
        raise InvalidInput('supply exactly one report_id or request_id')
    with store.archive() as conn:
        if report_id is None:
            request_id = require_name(request_id, 'request_id')
            row = conn.execute(
                'SELECT report_id FROM reports WHERE request_id = ?', (request_id,)
            ).fetchone()
            if row is None:
                return None
            report_id = row['report_id']
        else:
            report_id = require_name(report_id, 'report_id')
        return _load_pair(conn, report_id)


def read_publication_outcome(conn, request_id, *, attempt_id=None):
    sql = '''
        SELECT a.attempt_id, a.request_id, a.state, a.original_id, q.shift_id, q.ticket_id
        FROM publication_attempts AS a
        JOIN publication_requests AS q USING (request_id)
        WHERE a.request_id = ?
    '''
    if attempt_id is None:
        row = conn.execute(sql + ' ORDER BY a.attempt_id DESC LIMIT 1', (request_id,)).fetchone()
    else:
        row = conn.execute(sql + ' AND a.attempt_id = ?', (request_id, attempt_id)).fetchone()
    if row is None:
        return None
    publication = None
    if row['state'] == 'committed':
        report_key = conn.execute(
            'SELECT report_id FROM reports WHERE attempt_id = ?', (row['attempt_id'],)
        ).fetchone()
        if report_key is None:
            raise IntegrityViolation('successful attempt has no frozen report')
        publication = _load_pair(conn, report_key['report_id'])
        report = publication.report
        binding = (report.request_id, report.shift_id, report.ticket_id, report.original_id)
        expected = (request_id, row['shift_id'], row['ticket_id'], row['original_id'])
        if binding != expected:
            raise IntegrityViolation('frozen report and publication outcome disagree')
    return PublicationOutcome(**dict(row), publication=publication)


def list_shift_publications(conn, shift_id):
    rows = conn.execute('SELECT request_id, attempt_id FROM reports WHERE shift_id = ?', (shift_id,))
    outcomes = []
    for row in rows:
        outcome = read_publication_outcome(conn, row['request_id'], attempt_id=row['attempt_id'])
        if outcome is None or outcome.publication is None:
            raise IntegrityViolation('report has no matching successful publication outcome')
        outcomes.append(outcome)
    return tuple(outcomes)
