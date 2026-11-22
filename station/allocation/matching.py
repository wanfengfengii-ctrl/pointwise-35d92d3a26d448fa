from collections import deque

from station.protocol.eligibility import eligible_for_ticket


def build_candidate_graph(revision, shift, tickets, originals, occupied=()):
    occupied = frozenset(occupied)
    available = tuple(original for original in originals if original.original_id not in occupied)
    return {
        ticket.ticket_id: tuple(
            original.original_id for original in available
            if eligible_for_ticket(revision, shift, ticket, original)
        )
        for ticket in tickets
    }


def find_covering_assignment(graph, fixed=None):
    """Return a complete injection extending fixed edges, or None."""
    assignment = dict(fixed or {})
    blocked = set(assignment.values())
    if len(blocked) != len(assignment) or any(
        item not in graph.get(ticket, ()) for ticket, item in assignment.items()
    ):
        return None

    owners = {}
    for ticket in graph:
        if ticket in assignment:
            continue
        queue = deque([ticket])
        seen = {ticket}
        parents = {}
        free = None
        while queue and free is None:
            current = queue.popleft()
            for item in graph[current]:
                if item in blocked or item in parents:
                    continue
                parents[item] = current
                owner = owners.get(item)
                if owner is None:
                    free = item
                    break
                if owner not in seen:
                    seen.add(owner)
                    queue.append(owner)
        if free is None:
            return None
        while free is not None:
            current = parents[free]
            owners[free] = current
            free, assignment[current] = assignment.get(current), free
    return assignment
