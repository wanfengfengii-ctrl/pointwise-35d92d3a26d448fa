from dataclasses import dataclass

from station.allocation.commitments import SealClaim, ShiftTicket, load_shift_commitments
from station.allocation.shifts import Shift, get_shift


@dataclass(frozen=True)
class ShiftRoster:
    shift: Shift
    tickets: tuple[ShiftTicket, ...]
    claims: tuple[SealClaim, ...]


def load_shift_roster(conn, shift_id):
    shift = get_shift(conn, shift_id)
    commitments = load_shift_commitments(conn, shift_id)
    return ShiftRoster(shift, commitments.tickets, commitments.claims)
