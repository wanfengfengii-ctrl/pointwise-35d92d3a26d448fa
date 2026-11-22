from dataclasses import dataclass
from datetime import datetime, timezone

from station.database import InvalidInput, require_name


SUPPORTED_QUALITY_CODES = frozenset({'ok', 'review'})


@dataclass(frozen=True)
class SamplingCoverage:
    sites: tuple[str, ...]
    start: str
    end: str


def normalize_sample_time(value):
    if not isinstance(value, str):
        raise InvalidInput('sample time must be ISO 8601 text with a time zone')
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError('missing time zone')
        return parsed.astimezone(timezone.utc).isoformat(timespec='microseconds')
    except (ValueError, OverflowError) as exc:
        raise InvalidInput('sample time must be ISO 8601 text with a time zone') from exc


def normalize_names(values, field):
    if not isinstance(values, (list, tuple, set, frozenset)) or not values:
        raise InvalidInput(f'{field} must be a nonempty collection of names')
    return tuple(sorted({require_name(value, field) for value in values}))


def build_sampling_coverage(sites, start, end):
    coverage = SamplingCoverage(
        normalize_names(sites, 'sites'), normalize_sample_time(start), normalize_sample_time(end)
    )
    if coverage.start > coverage.end:
        raise InvalidInput('sampling window has reversed endpoints')
    return coverage


def matches_sampling_coverage(coverage, site, sample_time):
    return site in coverage.sites and coverage.start <= sample_time <= coverage.end
