from collections import Counter
from dataclasses import dataclass

from station.audit.reconciliation import AccountLine


@dataclass(frozen=True)
class ShiftTotals:
    ticket_count: int
    publication_count: int
    distinct_original_count: int
    duplicate_original_ids: tuple[int, ...]


def summarize_shift_totals(ticket_count, lines: tuple[AccountLine, ...]):
    originals = Counter(line.original_id for line in lines)
    duplicates = tuple(sorted(original_id for original_id, count in originals.items() if count > 1))
    return ShiftTotals(ticket_count, len(lines), len(originals), duplicates)
