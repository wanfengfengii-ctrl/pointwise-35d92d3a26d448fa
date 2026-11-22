from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json

from station.database import Conflict, InvalidInput, NotFound, require_name
from station.protocol.ranges import ConcentrationRange, build_concentration_range
from station.protocol.sampling import (
    SUPPORTED_QUALITY_CODES,
    SamplingCoverage,
    build_sampling_coverage,
    normalize_names,
)


@dataclass(frozen=True)
class ProjectRule:
    name: str
    unit: str
    concentration: ConcentrationRange
    coverage: SamplingCoverage
    qualities: tuple[str, ...]


@dataclass(frozen=True)
class ProtocolRevision:
    revision_id: str
    projects: tuple[ProjectRule, ...]

    def project(self, name):
        for rule in self.projects:
            if rule.name == name:
                return rule
        raise InvalidInput(f'project {name} is absent from revision {self.revision_id}')


def ensure_protocol_schema(conn):
    conn.execute('''
        CREATE TABLE IF NOT EXISTS protocol_revisions (
            revision_id TEXT PRIMARY KEY,
            projects TEXT NOT NULL
        )
    ''')


def _build_rule(name, raw):
    if not isinstance(raw, Mapping):
        raise InvalidInput(f'project {name} must be a mapping')
    try:
        unit = raw['unit']
        bounds = build_concentration_range(raw['min'], raw['max'], unit)
        coverage = build_sampling_coverage(raw['sites'], raw['start'], raw['end'])
        qualities = normalize_names(raw['qualities'], 'qualities')
    except KeyError as exc:
        raise InvalidInput(f'project {name} is missing {exc.args[0]}') from exc
    if not set(qualities) <= SUPPORTED_QUALITY_CODES:
        raise InvalidInput(f'project {name} has an unknown quality code')
    return ProjectRule(name, unit, bounds, coverage, qualities)


def register_protocol(store, revision_id, projects):
    revision_id = require_name(revision_id, 'revision_id')
    if not isinstance(projects, Mapping) or not projects:
        raise InvalidInput('a revision needs at least one named project')
    rules = [_build_rule(require_name(name, 'project'), raw) for name, raw in projects.items()]
    rules.sort(key=lambda rule: rule.name)
    payload = json.dumps([asdict(rule) for rule in rules], ensure_ascii=False, sort_keys=True)
    with store.operations(write=True) as conn:
        prior = conn.execute(
            'SELECT projects FROM protocol_revisions WHERE revision_id = ?', (revision_id,)
        ).fetchone()
        if prior is None:
            conn.execute('INSERT INTO protocol_revisions VALUES (?, ?)', (revision_id, payload))
        elif json.loads(prior['projects']) != json.loads(payload):
            raise Conflict(f'revision {revision_id} already has different rules')
    return revision_id


def get_protocol_revision(conn, revision_id):
    row = conn.execute(
        'SELECT projects FROM protocol_revisions WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f'revision {revision_id} does not exist')
    rules = []
    for item in json.loads(row['projects']):
        coverage = item['coverage']
        rules.append(ProjectRule(
            item['name'], item['unit'], ConcentrationRange(**item['concentration']),
            SamplingCoverage(tuple(coverage['sites']), coverage['start'], coverage['end']),
            tuple(item['qualities']),
        ))
    return ProtocolRevision(revision_id, tuple(rules))
