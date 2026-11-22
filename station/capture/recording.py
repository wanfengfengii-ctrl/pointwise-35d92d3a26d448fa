from collections.abc import Mapping
from dataclasses import dataclass

from station.capture.provenance import ReadingProvenance, capture_token, recording_identity
from station.database import Conflict, InvalidInput, require_name
from station.protocol.normalization import to_micrograms_per_liter
from station.protocol.sampling import SUPPORTED_QUALITY_CODES, normalize_sample_time


@dataclass(frozen=True)
class RecordedReading:
    provenance: ReadingProvenance
    value_ug_l: int


def _fields(raw, names):
    if not isinstance(raw, Mapping):
        raise InvalidInput('a recording row must be a mapping')
    try:
        return tuple(raw[name] for name in names)
    except KeyError as exc:
        raise InvalidInput(f'missing recording field {exc.args[0]}') from exc


def _position(raw):
    (position,) = _fields(raw, ('position',))
    if type(position) is not int or not 1 <= position <= 2**63 - 1:
        raise InvalidInput('position must be a positive recording sequence integer')
    return position


def parse_recorded_reading(source, raw):
    number, site, sampled_at, value, unit, quality = _fields(
        raw, ('original_no', 'site', 'sampled_at', 'value', 'unit', 'quality')
    )
    identity = recording_identity(source, number)
    site = require_name(site, 'site')
    quality = require_name(quality, 'quality')
    if quality not in SUPPORTED_QUALITY_CODES:
        raise InvalidInput(f'unknown quality code {quality}')
    sample_time = normalize_sample_time(sampled_at)
    value_ug_l = to_micrograms_per_liter(value, unit)
    provenance = ReadingProvenance(
        identity.source, identity.original_no, _position(raw), site,
        sampled_at, sample_time, str(value), unit, quality,
    )
    return RecordedReading(provenance, value_ug_l)


def read_device_order(source, records):
    source = require_name(source, 'source')
    ordered = sorted(records, key=_position)
    positions = [_position(raw) for raw in ordered]
    if len(set(positions)) != len(positions):
        raise Conflict('the recording repeats a sequence position')
    for raw in ordered:
        yield parse_recorded_reading(source, raw)


class DeviceRecording:
    """A finite recording that clears a pending row when it is acknowledged."""

    def __init__(self, source_id, records):
        self.source_id = require_name(source_id, 'source')
        self._pending = {}
        self._acknowledgments = {}
        for raw in records:
            (number,) = _fields(raw, ('original_no',))
            identity = recording_identity(self.source_id, number)
            if identity in self._pending:
                raise Conflict('the device recording repeats an original number')
            self._pending[identity] = dict(raw)

    def read_pending(self):
        return tuple(dict(raw) for raw in self._pending.values())

    @property
    def acknowledgments(self):
        return tuple(self._acknowledgments.values())

    def acknowledge(self, acknowledgment):
        identity = acknowledgment.identity
        if (
            identity.source != self.source_id
            or acknowledgment.token != capture_token(identity)
        ):
            raise Conflict('acknowledgment belongs to another source original')
        previous = self._acknowledgments.get(identity)
        if previous is not None:
            if previous != acknowledgment:
                raise Conflict('source original already has a different acknowledgment')
            return
        if identity not in self._pending:
            raise Conflict('source original is unknown to this recording')
        self._acknowledgments[identity] = acknowledgment
        del self._pending[identity]
