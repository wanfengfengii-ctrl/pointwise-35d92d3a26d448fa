from dataclasses import dataclass

from station.database import IntegrityViolation, NotFound


@dataclass(frozen=True)
class ShiftTicket:
    shift_id: str
    ticket_id: str
    ordinal: int
    project: str
    start: str
    end: str


@dataclass(frozen=True)
class SealClaim:
    attempt_id: int
    shift_id: str
    ticket_id: str
    request_id: str
    original_id: int
    state: str


@dataclass(frozen=True)
class ShiftCommitments:
    tickets: tuple[ShiftTicket, ...]
    claims: tuple[SealClaim, ...]

    @property
    def occupied_originals(self):
        return frozenset(claim.original_id for claim in self.claims)

    @property
    def waiting_tickets(self):
        claimed = {claim.ticket_id for claim in self.claims}
        return tuple(ticket for ticket in self.tickets if ticket.ticket_id not in claimed)


def ensure_commitment_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS tickets (
            shift_id TEXT NOT NULL REFERENCES shifts(shift_id),
            ticket_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal > 0),
            project TEXT NOT NULL,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            PRIMARY KEY (shift_id, ticket_id),
            UNIQUE (shift_id, ordinal),
            CHECK (start <= end)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS seal_claims (
            attempt_id INTEGER PRIMARY KEY,
            shift_id TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            request_id TEXT NOT NULL UNIQUE,
            original_id INTEGER NOT NULL UNIQUE,
            state TEXT NOT NULL CHECK (state IN ('pending', 'committed')),
            UNIQUE (shift_id, ticket_id),
            FOREIGN KEY (shift_id, ticket_id) REFERENCES tickets(shift_id, ticket_id),
            FOREIGN KEY (shift_id, original_id) REFERENCES originals(shift_id, original_id)
        )
    ''')


def find_ticket(conn, shift_id, ticket_id):
    row = conn.execute(
        'SELECT * FROM tickets WHERE shift_id = ? AND ticket_id = ?', (shift_id, ticket_id)
    ).fetchone()
    return None if row is None else ShiftTicket(**dict(row))


def get_ticket(conn, shift_id, ticket_id):
    ticket = find_ticket(conn, shift_id, ticket_id)
    if ticket is None:
        raise NotFound(f'ticket {shift_id}/{ticket_id} is not admitted')
    return ticket


def find_ticket_claim(conn, shift_id, ticket_id):
    row = conn.execute(
        'SELECT * FROM seal_claims WHERE shift_id = ? AND ticket_id = ?', (shift_id, ticket_id)
    ).fetchone()
    return None if row is None else SealClaim(**dict(row))


def load_shift_commitments(conn, shift_id):
    tickets = conn.execute('SELECT * FROM tickets WHERE shift_id = ? ORDER BY ordinal', (shift_id,))
    claims = conn.execute('SELECT * FROM seal_claims WHERE shift_id = ?', (shift_id,))
    return ShiftCommitments(
        tuple(ShiftTicket(**dict(row)) for row in tickets),
        tuple(SealClaim(**dict(row)) for row in claims),
    )


def record_admission(conn, ticket):
    conn.execute('INSERT INTO tickets VALUES (?, ?, ?, ?, ?, ?)', (
        ticket.shift_id, ticket.ticket_id, ticket.ordinal, ticket.project, ticket.start, ticket.end
    ))
    return ticket


def record_seal_claim(conn, claim):
    conn.execute('INSERT INTO seal_claims VALUES (?, ?, ?, ?, ?, ?)', (
        claim.attempt_id, claim.shift_id, claim.ticket_id, claim.request_id,
        claim.original_id, claim.state,
    ))
    return claim


def resolve_seal_claim(conn, expected, committed):
    current = find_ticket_claim(conn, expected.shift_id, expected.ticket_id)
    if current != expected:
        raise IntegrityViolation('seal claim changed before resolution')
    if current.state == 'committed':
        if not committed:
            raise IntegrityViolation('cannot release a committed original')
        return
    parameters = (expected.attempt_id, expected.request_id, expected.original_id)
    if committed:
        conn.execute('''
            UPDATE seal_claims SET state = 'committed'
            WHERE attempt_id = ? AND request_id = ? AND original_id = ? AND state = 'pending'
        ''', parameters)
    else:
        conn.execute('''
            DELETE FROM seal_claims
            WHERE attempt_id = ? AND request_id = ? AND original_id = ? AND state = 'pending'
        ''', parameters)
