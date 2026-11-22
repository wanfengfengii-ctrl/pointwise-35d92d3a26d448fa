from station.allocation.commitments import ShiftTicket, load_shift_commitments, record_admission
from station.allocation.matching import build_candidate_graph, find_covering_assignment
from station.allocation.shifts import get_shift
from station.capture.storage import list_shift_originals
from station.database import Conflict, InvalidInput, Pending, Unavailable, require_name
from station.protocol.revisions import get_protocol_revision
from station.protocol.sampling import normalize_sample_time


def _might_fit_after_failed_claims(revision, shift, commitments, proposed, originals):
    finished = tuple(claim for claim in commitments.claims if claim.state == 'committed')
    if len(finished) == len(commitments.claims):
        return False
    finished_tickets = {claim.ticket_id for claim in finished}
    remaining = tuple(ticket for ticket in commitments.tickets if ticket.ticket_id not in finished_tickets)
    graph = build_candidate_graph(
        revision, shift, (*remaining, proposed), originals,
        (claim.original_id for claim in finished),
    )
    return find_covering_assignment(graph) is not None


def admit_ticket(store, shift_id, ticket_id, project, *, start=None, end=None):
    shift_id = require_name(shift_id, 'shift_id')
    ticket_id = require_name(ticket_id, 'ticket_id')
    project = require_name(project, 'project')
    with store.operations(write=True) as conn:
        shift = get_shift(conn, shift_id)
        revision = get_protocol_revision(conn, shift.revision_id)
        rule = revision.project(project)
        start = rule.coverage.start if start is None else normalize_sample_time(start)
        end = rule.coverage.end if end is None else normalize_sample_time(end)
        if start > end:
            raise InvalidInput('ticket sampling window has reversed endpoints')
        commitments = load_shift_commitments(conn, shift_id)
        for ticket in commitments.tickets:
            if ticket.ticket_id == ticket_id:
                if (ticket.project, ticket.start, ticket.end) != (project, start, end):
                    raise Conflict(f'ticket {shift_id}/{ticket_id} already has other requirements')
                return ticket
        if shift.closed:
            raise Conflict(f'shift {shift_id} is closed to admissions')
        ordinal = commitments.tickets[-1].ordinal + 1 if commitments.tickets else 1
        proposed = ShiftTicket(shift_id, ticket_id, ordinal, project, start, end)
        originals = list_shift_originals(conn, shift_id)
        graph = build_candidate_graph(
            revision, shift, (*commitments.waiting_tickets, proposed), originals,
            commitments.occupied_originals,
        )
        if find_covering_assignment(graph) is None:
            if _might_fit_after_failed_claims(revision, shift, commitments, proposed, originals):
                raise Pending('admission depends on a seal with an unresolved outcome')
            raise Unavailable('no complete assignment can cover the proposed ticket')
        return record_admission(conn, proposed)
