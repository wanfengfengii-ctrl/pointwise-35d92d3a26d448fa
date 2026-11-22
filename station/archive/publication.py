from dataclasses import replace
import sqlite3

from station.allocation.commitments import get_ticket
from station.allocation.preview import preview_ticket
from station.allocation.settlement import prepare_seal, settle_seal_claim
from station.allocation.shifts import get_shift
from station.archive.receipts import build_first_receipt, ensure_receipt_schema, insert_first_receipt
from station.archive.reports import build_sealed_report, ensure_report_schema, insert_report
from station.archive.retrieval import read_publication_outcome
from station.database import (
    Conflict, IntegrityViolation, NotFound, Pending, SaveFailed, Unavailable, require_name, run_checkpoint,
)


def ensure_publication_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS publication_requests (
            request_id TEXT PRIMARY KEY,
            shift_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS publication_attempts (
            attempt_id INTEGER PRIMARY KEY,
            request_id TEXT NOT NULL REFERENCES publication_requests(request_id),
            state TEXT NOT NULL CHECK (state IN ('pending', 'failed', 'committed')),
            original_id INTEGER,
            CHECK (state != 'committed' OR original_id IS NOT NULL),
            CHECK (state != 'pending' OR original_id IS NULL)
        )
    ''')
    conn.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS active_attempt_per_request
        ON publication_attempts(request_id) WHERE state != 'failed'
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS publication_attempt_history
        ON publication_attempts(request_id, attempt_id)
    ''')
    ensure_report_schema(conn)
    ensure_receipt_schema(conn)


def _begin_attempt(store, request_id, shift_id, ticket_id):
    with store.archive(write=True) as conn:
        saved = conn.execute('SELECT * FROM publication_requests WHERE request_id = ?', (request_id,)).fetchone()
        if saved is None:
            with store.operations() as operations:
                get_ticket(operations, shift_id, ticket_id)
            conn.execute('INSERT INTO publication_requests VALUES (?, ?, ?)', (request_id, shift_id, ticket_id))
        elif (saved['shift_id'], saved['ticket_id']) != (shift_id, ticket_id):
            raise Conflict(f'publication request {request_id} already belongs to another ticket')
        previous = read_publication_outcome(conn, request_id)
        if previous is not None:
            if previous.state != 'failed':
                return previous
            settle_seal_claim(store, previous)
        row = conn.execute('''
            INSERT INTO publication_attempts (request_id, state) VALUES (?, 'pending')
        ''', (request_id,))
        return read_publication_outcome(conn, request_id, attempt_id=row.lastrowid)


def _current_attempt(conn, attempt):
    current = read_publication_outcome(conn, attempt.request_id, attempt_id=attempt.attempt_id)
    if current is None:
        raise IntegrityViolation('the durable publication attempt is missing')
    return current


def _prepare_attempt(store, attempt):
    if attempt.state != 'pending':
        return attempt, None
    claim = prepare_seal(
        store, attempt.shift_id, attempt.ticket_id, attempt.request_id, attempt.attempt_id
    )
    return attempt, claim


def _commit_attempt(store, attempt, claim, checkpoint):
    with store.archive(write=True) as conn:
        current = _current_attempt(conn, attempt)
        if current.state == 'committed':
            return current, False
        preview = preview_ticket(store, current.shift_id, current.ticket_id)
        if not preview.candidates:
            raise Unavailable('no visible original for publication')
        original = preview.candidates[0]
        with store.operations() as operations:
            shift = get_shift(operations, current.shift_id)
        selected = replace(claim, original_id=original.original_id)
        report = build_sealed_report(selected, shift.revision_id, original)
        insert_report(conn, report)
        run_checkpoint(checkpoint, 'before_receipt')
        insert_first_receipt(conn, build_first_receipt(report))
        conn.execute('''
            UPDATE publication_attempts SET state = 'committed', original_id = ?
            WHERE attempt_id = ?
        ''', (original.original_id, current.attempt_id))
        return _current_attempt(conn, attempt), True


def _record_failed_attempt(store, attempt, claim):
    with store.archive(write=True) as conn:
        current = _current_attempt(conn, attempt)
        if current.state != 'pending':
            return current
        original_id = claim.original_id if claim is not None else None
        conn.execute('''
            UPDATE publication_attempts SET state = 'failed', original_id = ?
            WHERE attempt_id = ?
        ''', (original_id, current.attempt_id))
        return _current_attempt(conn, attempt)


def _settle_known_outcome(store, outcome):
    try:
        settle_seal_claim(store, outcome)
    except sqlite3.Error as exc:
        raise Pending('publication outcome is durable and its claim awaits settlement') from exc


def seal_ticket(store, request_id, shift_id, ticket_id, *, checkpoint=None):
    request_id = require_name(request_id, 'request_id')
    shift_id = require_name(shift_id, 'shift_id')
    ticket_id = require_name(ticket_id, 'ticket_id')
    try:
        attempt = _begin_attempt(store, request_id, shift_id, ticket_id)
    except sqlite3.Error as exc:
        raise Pending('publication request registration needs reconciliation') from exc
    newly_committed = False
    claim = None
    cause = None
    try:
        outcome, claim = _prepare_attempt(store, attempt)
        if claim is not None:
            run_checkpoint(checkpoint, 'after_claim')
            outcome, newly_committed = _commit_attempt(store, attempt, claim, checkpoint)
    except (SaveFailed, sqlite3.Error) as exc:
        cause = exc
        try:
            outcome = _record_failed_attempt(store, attempt, claim)
        except sqlite3.Error as uncertain:
            raise Pending('archive could not establish a terminal outcome') from uncertain
    if newly_committed:
        run_checkpoint(checkpoint, 'after_archive_commit')
    _settle_known_outcome(store, outcome)
    if outcome.state == 'failed':
        raise SaveFailed(f'publication attempt {outcome.attempt_id} did not commit') from cause
    return outcome.publication


def reconcile_publication(store, request_id):
    request_id = require_name(request_id, 'request_id')
    try:
        with store.archive() as conn:
            outcome = read_publication_outcome(conn, request_id)
    except sqlite3.Error as exc:
        raise Pending('archive outcome is temporarily unavailable') from exc
    if outcome is None:
        raise NotFound(f'publication request {request_id} does not exist')
    _settle_known_outcome(store, outcome)
    return outcome
