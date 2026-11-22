from dataclasses import asdict, dataclass
import json

from station.allocation.shifts import mark_shift_closed
from station.audit.reconciliation import AccountLine, reconcile_shift
from station.audit.roster import load_shift_roster
from station.audit.totals import ShiftTotals, summarize_shift_totals
from station.capture.provenance import ReadingProvenance
from station.database import IntegrityViolation, Pending, require_name


@dataclass(frozen=True)
class ShiftAccount:
    shift_id: str
    site: str
    revision_id: str
    lines: tuple[AccountLine, ...]
    totals: ShiftTotals


def ensure_account_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS shift_accounts (
            shift_id TEXT PRIMARY KEY REFERENCES shifts(shift_id),
            payload TEXT NOT NULL
        )
    ''')


def _load_account(conn, shift_id):
    row = conn.execute('SELECT payload FROM shift_accounts WHERE shift_id = ?', (shift_id,)).fetchone()
    if row is None:
        return None
    fields = json.loads(row['payload'])
    lines = []
    for line in fields['lines']:
        line['provenance'] = ReadingProvenance(**line['provenance'])
        lines.append(AccountLine(**line))
    totals = fields['totals']
    totals['duplicate_original_ids'] = tuple(totals['duplicate_original_ids'])
    return ShiftAccount(
        fields['shift_id'], fields['site'], fields['revision_id'], tuple(lines), ShiftTotals(**totals)
    )


def close_and_read_shift(store, shift_id):
    shift_id = require_name(shift_id, 'shift_id')
    with store.operations() as operations:
        existing = _load_account(operations, shift_id)
        if existing is not None:
            return existing

    # Guard the archive before taking the operations writer. Closure then
    # sees a stable pair of stores and freezes the roster under its own lock.
    with store.archive(write=True) as archive, store.operations(write=True) as operations:
        existing = _load_account(operations, shift_id)
        if existing is not None:
            return existing
        roster = load_shift_roster(operations, shift_id)
        if roster.shift.closed:
            raise IntegrityViolation('closed shift is missing its frozen account')
        result = reconcile_shift(operations, archive, roster)
        if result.open_tickets:
            raise Pending('tickets awaiting settlement: ' + ', '.join(result.open_tickets))
        totals = summarize_shift_totals(len(roster.tickets), result.lines)
        if totals.duplicate_original_ids:
            raise IntegrityViolation('an original was used more than once in the shift')
        account = ShiftAccount(
            shift_id, roster.shift.site, roster.shift.revision_id, result.lines, totals
        )
        operations.execute('INSERT INTO shift_accounts VALUES (?, ?)', (
            shift_id, json.dumps(asdict(account), ensure_ascii=False)
        ))
        mark_shift_closed(operations, shift_id)
        return account
