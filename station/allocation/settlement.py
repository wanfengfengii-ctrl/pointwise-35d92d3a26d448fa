from typing import TYPE_CHECKING

from station.allocation.commitments import (
    SealClaim, find_ticket_claim, get_ticket, record_seal_claim, resolve_seal_claim,
)
from station.allocation.preview import preview_ticket
from station.allocation.shifts import get_shift
from station.database import Conflict, IntegrityViolation, Pending, Unavailable

if TYPE_CHECKING:
    from station.archive.retrieval import PublicationOutcome


def get_active_seal_claim(conn, shift_id, ticket_id):
    return find_ticket_claim(conn, shift_id, ticket_id)


def prepare_seal(store, shift_id, ticket_id, request_id, attempt_id):
    with store.operations() as conn:
        shift = get_shift(conn, shift_id)
        get_ticket(conn, shift_id, ticket_id)
        existing = get_active_seal_claim(conn, shift_id, ticket_id)
        if existing is not None:
            if existing.state == 'committed':
                raise Conflict(f'ticket {shift_id}/{ticket_id} is already signed')
            if (existing.request_id, existing.attempt_id) == (request_id, attempt_id):
                return existing
            raise Pending('an earlier request still holds this ticket')
        if shift.closed:
            raise Conflict(f'shift {shift_id} is closed to signing')
    preview = preview_ticket(store, shift_id, ticket_id)
    if not preview.candidates:
        raise Unavailable('no visible original for this ticket')
    return SealClaim(attempt_id, shift_id, ticket_id, request_id,
                     preview.candidates[0].original_id, 'pending')


def settle_seal_claim(store, outcome: 'PublicationOutcome'):
    if outcome.state == 'pending':
        raise Pending('the archive has yet to determine the seal outcome')
    with store.operations(write=True) as conn:
        claim = get_active_seal_claim(conn, outcome.shift_id, outcome.ticket_id)
        if claim is None:
            if outcome.state == 'committed':
                record_seal_claim(conn, SealClaim(
                    outcome.attempt_id, outcome.shift_id, outcome.ticket_id,
                    outcome.request_id, outcome.original_id, 'committed',
                ))
            return
        if claim.attempt_id != outcome.attempt_id:
            if outcome.state == 'failed':
                return
            raise IntegrityViolation('committed outcome belongs to another attempt')
        if (claim.request_id, claim.original_id) != (outcome.request_id, outcome.original_id):
            raise IntegrityViolation('archive outcome differs from the occupied original')
        resolve_seal_claim(conn, claim, committed=outcome.state == 'committed')
