from station.protocol.sampling import matches_sampling_coverage


def _matches_rule(rule, reading, site):
    provenance = reading.provenance
    return (
        provenance.site == site
        and matches_sampling_coverage(rule.coverage, site, provenance.sample_time)
        and provenance.quality in rule.qualities
        and rule.concentration.contains(reading.value_ug_l)
    )


def eligible_projects(revision, reading, site):
    return tuple(rule.name for rule in revision.projects if _matches_rule(rule, reading, site))


def eligible_for_ticket(revision, shift, ticket, reading):
    return (
        reading.shift_id == ticket.shift_id == shift.shift_id
        and ticket.start <= reading.provenance.sample_time <= ticket.end
        and _matches_rule(revision.project(ticket.project), reading, shift.site)
    )
