from dataclasses import dataclass
import json

from station.database import require_name


@dataclass(frozen=True)
class RecordingIdentity:
    source: str
    original_no: str


@dataclass(frozen=True)
class ReadingProvenance:
    source: str
    original_no: str
    position: int
    site: str
    sampled_at: str
    sample_time: str
    raw_value: str
    raw_unit: str
    quality: str

    @property
    def identity(self):
        return recording_identity(self.source, self.original_no)


def recording_identity(source, original_no):
    return RecordingIdentity(
        require_name(source, 'source'), require_name(original_no, 'original_no')
    )


def capture_token(identity):
    encoded = json.dumps([identity.source, identity.original_no], separators=(',', ':'))
    return 'capture:' + encoded
