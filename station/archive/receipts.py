from dataclasses import dataclass

from station.archive.reports import SealedReport


@dataclass(frozen=True)
class FirstReceipt:
    receipt_id: str
    request_id: str
    report_id: str


def ensure_receipt_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS first_receipts (
            receipt_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE REFERENCES publication_requests(request_id),
            report_id TEXT NOT NULL UNIQUE REFERENCES reports(report_id)
        )
    ''')


def build_first_receipt(report: SealedReport):
    return FirstReceipt(f'receipt:{report.request_id}', report.request_id, report.report_id)


def insert_first_receipt(conn, receipt):
    conn.execute('INSERT INTO first_receipts VALUES (?, ?, ?)', (
        receipt.receipt_id, receipt.request_id, receipt.report_id
    ))


def load_first_receipt(conn, report_id):
    row = conn.execute('SELECT * FROM first_receipts WHERE report_id = ?', (report_id,)).fetchone()
    return None if row is None else FirstReceipt(**dict(row))
