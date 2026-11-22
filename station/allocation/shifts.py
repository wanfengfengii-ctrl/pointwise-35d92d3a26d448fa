from dataclasses import dataclass

from station.database import Conflict, NotFound, require_name
from station.protocol.revisions import get_protocol_revision


@dataclass(frozen=True)
class Shift:
    shift_id: str
    site: str
    revision_id: str
    closed: bool


def ensure_shift_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS shifts (
            shift_id TEXT PRIMARY KEY,
            site TEXT NOT NULL,
            revision_id TEXT NOT NULL REFERENCES protocol_revisions(revision_id),
            closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1))
        )
    ''')


def _shift(row):
    return Shift(row['shift_id'], row['site'], row['revision_id'], bool(row['closed']))


def open_shift(store, shift_id, site, revision_id):
    shift_id = require_name(shift_id, 'shift_id')
    site = require_name(site, 'site')
    revision_id = require_name(revision_id, 'revision_id')
    with store.operations(write=True) as conn:
        row = conn.execute('SELECT * FROM shifts WHERE shift_id = ?', (shift_id,)).fetchone()
        if row is not None:
            existing = _shift(row)
            if (existing.site, existing.revision_id) != (site, revision_id):
                raise Conflict(f'shift {shift_id} already has a different site or revision')
            return existing
        get_protocol_revision(conn, revision_id)
        conn.execute(
            'INSERT INTO shifts (shift_id, site, revision_id) VALUES (?, ?, ?)',
            (shift_id, site, revision_id),
        )
        return Shift(shift_id, site, revision_id, False)


def get_shift(conn, shift_id):
    row = conn.execute('SELECT * FROM shifts WHERE shift_id = ?', (shift_id,)).fetchone()
    if row is None:
        raise NotFound(f'shift {shift_id} does not exist')
    return _shift(row)


def mark_shift_closed(conn, shift_id):
    changed = conn.execute('UPDATE shifts SET closed = 1 WHERE shift_id = ?', (shift_id,))
    if changed.rowcount != 1:
        raise NotFound(f'shift {shift_id} does not exist')
    return get_shift(conn, shift_id)
