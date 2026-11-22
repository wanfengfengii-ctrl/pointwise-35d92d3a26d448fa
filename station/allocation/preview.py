from dataclasses import dataclass

from station.allocation.commitments import ShiftTicket, get_ticket, load_shift_commitments
from station.allocation.shifts import get_shift
from station.capture.storage import StoredReading, list_shift_originals
from station.database import require_name
from station.protocol.eligibility import eligible_for_ticket
from station.protocol.revisions import get_protocol_revision


@dataclass(frozen=True)
class TicketPreview:
    ticket: ShiftTicket
    candidates: tuple[StoredReading, ...]


def preview_ticket(store, shift_id, ticket_id):
    shift_id = require_name(shift_id, 'shift_id')
    ticket_id = require_name(ticket_id, 'ticket_id')
    with store.operations() as conn:
        shift = get_shift(conn, shift_id)
        ticket = get_ticket(conn, shift_id, ticket_id)
        revision = get_protocol_revision(conn, shift.revision_id)
        commitments = load_shift_commitments(conn, shift_id)
        if shift.closed or any(
            claim.ticket_id == ticket_id and claim.state == 'committed'
            for claim in commitments.claims
        ):
            return TicketPreview(ticket, ())
        occupied = {claim.original_id for claim in commitments.claims if claim.ticket_id != ticket_id}
        candidates = tuple(
            original for original in list_shift_originals(conn, shift_id)
            if original.original_id not in occupied
            and eligible_for_ticket(revision, shift, ticket, original)
        )
        return TicketPreview(ticket, candidates)
