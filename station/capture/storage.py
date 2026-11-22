from dataclasses import asdict, dataclass
import json

from station.capture.provenance import ReadingProvenance, capture_token
from station.database import Conflict, NotFound


@dataclass(frozen=True)
class StoredReading:
    original_id: int
    shift_id: str
    provenance: ReadingProvenance
    value_ug_l: int
    acknowledgment_token: str


def ensure_capture_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS originals (
            original_id INTEGER PRIMARY KEY,
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            source TEXT NOT NULL,
            original_no TEXT NOT NULL,
            position INTEGER NOT NULL CHECK (position > 0),
            provenance TEXT NOT NULL,
            value_ug_l TEXT NOT NULL,
            acknowledgment_token TEXT NOT NULL,
            UNIQUE (source, original_no),
            UNIQUE (source, position),
            UNIQUE (shift_id, original_id)
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS originals_by_shift
        ON originals(shift_id, source, position)
    ''')


def _stored(row):
    return StoredReading(
        row['original_id'], row['shift_id'],
        ReadingProvenance(**json.loads(row['provenance'])),
        int(row['value_ug_l']), row['acknowledgment_token'],
    )


def find_captured_source(conn, identity):
    row = conn.execute(
        'SELECT * FROM originals WHERE source = ? AND original_no = ?',
        (identity.source, identity.original_no),
    ).fetchone()
    return None if row is None else _stored(row)


def require_same_original(stored, recorded):
    if (stored.provenance, stored.value_ug_l) != (recorded.provenance, recorded.value_ug_l):
        raise Conflict('the same source original number carries different data')
    return stored


def store_original(conn, shift_id, recorded):
    provenance = recorded.provenance
    identity = provenance.identity
    previous = find_captured_source(conn, identity)
    if previous is not None:
        return require_same_original(previous, recorded)
    sequence = conn.execute(
        'SELECT original_no FROM originals WHERE source = ? AND position = ?',
        (identity.source, provenance.position),
    ).fetchone()
    if sequence is not None:
        raise Conflict('this recording position belongs to another original')
    token = capture_token(identity)
    result = conn.execute('''
        INSERT INTO originals (
            shift_id, source, original_no, position, provenance, value_ug_l,
            acknowledgment_token
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (shift_id, identity.source, identity.original_no, provenance.position,
          json.dumps(asdict(provenance), ensure_ascii=False), str(recorded.value_ug_l), token))
    return StoredReading(result.lastrowid, shift_id, provenance, recorded.value_ug_l, token)


def get_original(conn, original_id):
    row = conn.execute('SELECT * FROM originals WHERE original_id = ?', (original_id,)).fetchone()
    if row is None:
        raise NotFound(f'original {original_id} does not exist')
    return _stored(row)


def list_shift_originals(conn, shift_id):
    rows = conn.execute('''
        SELECT * FROM originals WHERE shift_id = ? ORDER BY source, position
    ''', (shift_id,))
    return tuple(_stored(row) for row in rows)
