from dataclasses import dataclass

from station.archive.retrieval import list_shift_publications
from station.audit.roster import ShiftRoster
from station.capture.provenance import ReadingProvenance
from station.capture.storage import get_original
from station.database import IntegrityViolation


@dataclass(frozen=True)
class AccountLine:
    ordinal: int
    ticket_id: str
    project: str
    request_id: str
    report_id: str
    receipt_id: str
    original_id: int
    value_ug_l: int
    provenance: ReadingProvenance


@dataclass(frozen=True)
class ReconciliationResult:
    lines: tuple[AccountLine, ...]
    open_tickets: tuple[str, ...]


def _reconcile_line(operations, shift, ticket, claim, outcome):
    publication = outcome.publication
    report, receipt = publication.report, publication.receipt
    actual = (outcome.attempt_id, report.request_id, report.original_id, report.revision_id)
    expected = (claim.attempt_id, claim.request_id, claim.original_id, shift.revision_id)
    if actual != expected:
        raise IntegrityViolation(f'publication and claim disagree for {ticket.ticket_id}')
    original = get_original(operations, claim.original_id)
    if (original.shift_id, original.value_ug_l, original.provenance) != (
        shift.shift_id, report.value_ug_l, report.provenance
    ):
        raise IntegrityViolation(f'report differs from the captured original for {ticket.ticket_id}')
    return AccountLine(
        ticket.ordinal, ticket.ticket_id, ticket.project, report.request_id, report.report_id,
        receipt.receipt_id, report.original_id, report.value_ug_l, report.provenance,
    )


def reconcile_shift(operations, archive, roster: ShiftRoster):
    outcomes = {}
    formal_tickets = {ticket.ticket_id for ticket in roster.tickets}
    for outcome in list_shift_publications(archive, roster.shift.shift_id):
        if outcome.ticket_id not in formal_tickets or outcome.ticket_id in outcomes:
            raise IntegrityViolation('archive contains an unexpected report for the shift')
        outcomes[outcome.ticket_id] = outcome
    claims = {claim.ticket_id: claim for claim in roster.claims}
    lines = []
    open_tickets = []
    for ticket in roster.tickets:
        claim = claims.get(ticket.ticket_id)
        outcome = outcomes.get(ticket.ticket_id)
        if outcome is not None and (claim is None or outcome.original_id != claim.original_id):
            raise IntegrityViolation(f'archive lacks the correct claim for {ticket.ticket_id}')
        if claim is None or claim.state != 'committed':
            open_tickets.append(ticket.ticket_id)
            continue
        if outcome is None:
            raise IntegrityViolation(f'settled ticket {ticket.ticket_id} has no successful outcome')
        lines.append(_reconcile_line(operations, roster.shift, ticket, claim, outcome))
    return ReconciliationResult(tuple(lines), tuple(open_tickets))
