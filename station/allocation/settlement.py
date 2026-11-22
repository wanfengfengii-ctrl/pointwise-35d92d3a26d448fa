from typing import TYPE_CHECKING

from station.allocation.commitments import (
    SealClaim, find_ticket_claim, get_ticket, load_shift_commitments,
    record_seal_claim, resolve_seal_claim,
)
from station.allocation.matching import build_candidate_graph, find_covering_assignment
from station.allocation.shifts import get_shift
from station.capture.storage import list_shift_originals
from station.database import Conflict, IntegrityViolation, Pending, Unavailable
from station.protocol.eligibility import eligible_for_ticket
from station.protocol.revisions import get_protocol_revision

if TYPE_CHECKING:
    from station.archive.retrieval import PublicationOutcome


def get_active_seal_claim(conn, shift_id, ticket_id):
    return find_ticket_claim(conn, shift_id, ticket_id)


def preserves_assignment(revision, shift, commitments, ticket, original, originals):
    """Whether fixing ``original`` to ``ticket`` leaves every other open ticket covered.

    Tickets that already hold a claim keep their own original (a pending claim is
    still an exclusive occupation until its outcome is known).  Tickets without a
    claim are free to be assigned in any order, so the complete residual roster is
    recomputed instead of trusting a preview.
    """
    occupied = frozenset(
        claim.original_id for claim in commitments.claims
        if claim.ticket_id != ticket.ticket_id
    )
    claimed = {claim.ticket_id for claim in commitments.claims}
    open_tickets = tuple(
        item for item in commitments.tickets
        if item.ticket_id != ticket.ticket_id and item.ticket_id not in claimed
    )
    graph = build_candidate_graph(
        revision, shift, (*open_tickets, ticket), originals, occupied
    )
    return find_covering_assignment(graph, {ticket.ticket_id: original.original_id}) is not None


def _choose_original(conn, shift, revision, ticket):
    commitments = load_shift_commitments(conn, shift.shift_id)
    originals = list_shift_originals(conn, shift.shift_id)
    occupied = frozenset(claim.original_id for claim in commitments.claims)
    for original in originals:
        if original.original_id in occupied:
            continue
        if not eligible_for_ticket(revision, shift, ticket, original):
            continue
        if preserves_assignment(revision, shift, commitments, ticket, original, originals):
            return original
    return None


def _might_fit_after_pending_claims(revision, shift, commitments, ticket, originals):
    """Whether an unresolved claim is the only thing standing between this ticket and a seal.

    A pending claim still occupies its original.  If, with those occupations
    lifted, the whole open roster could be covered, the block is only provisional
    and the caller must wait for the outcome rather than report no stock.
    """
    if not any(claim.state == 'pending' for claim in commitments.claims):
        return False
    committed_tickets = {
        claim.ticket_id for claim in commitments.claims if claim.state == 'committed'
    }
    blocked = frozenset(
        claim.original_id for claim in commitments.claims if claim.state == 'committed'
    )
    open_tickets = tuple(
        item for item in commitments.tickets
        if item.ticket_id != ticket.ticket_id and item.ticket_id not in committed_tickets
    )
    graph = build_candidate_graph(
        revision, shift, (*open_tickets, ticket), originals, blocked
    )
    return find_covering_assignment(graph) is not None


def prepare_seal(store, shift_id, ticket_id, request_id, attempt_id):
    with store.operations(write=True) as conn:
        shift = get_shift(conn, shift_id)
        ticket = get_ticket(conn, shift_id, ticket_id)
        existing = get_active_seal_claim(conn, shift_id, ticket_id)
        if existing is not None:
            if existing.state == 'committed':
                raise Conflict(f'ticket {shift_id}/{ticket_id} is already signed')
            if (existing.request_id, existing.attempt_id) == (request_id, attempt_id):
                return existing
            raise Pending('an earlier request still holds this ticket')
        if shift.closed:
            raise Conflict(f'shift {shift_id} is closed to signing')
        revision = get_protocol_revision(conn, shift.revision_id)
        original = _choose_original(conn, shift, revision, ticket)
        if original is None:
            commitments = load_shift_commitments(conn, shift_id)
            originals = list_shift_originals(conn, shift_id)
            if _might_fit_after_pending_claims(revision, shift, commitments, ticket, originals):
                raise Pending('signing depends on a seal with an unresolved outcome')
            raise Unavailable('no visible original for this ticket')
        claim = SealClaim(
            attempt_id, shift_id, ticket_id, request_id, original.original_id, 'pending'
        )
        return record_seal_claim(conn, claim)


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
