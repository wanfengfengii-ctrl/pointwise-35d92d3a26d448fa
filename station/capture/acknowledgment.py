from dataclasses import dataclass

from station.capture.provenance import RecordingIdentity, capture_token
from station.capture.storage import StoredReading
from station.database import Conflict, IntegrityViolation


@dataclass(frozen=True)
class CaptureAcknowledgment:
    identity: RecordingIdentity
    original_id: int
    shift_id: str
    token: str


def restore_acknowledgment(stored: StoredReading):
    identity = stored.provenance.identity
    if stored.acknowledgment_token != capture_token(identity):
        raise IntegrityViolation('stored capture acknowledgment has the wrong source identity')
    return CaptureAcknowledgment(
        identity, stored.original_id, stored.shift_id, stored.acknowledgment_token
    )


def confirm_source_release(source, stored):
    acknowledgment = restore_acknowledgment(stored)
    if source.source_id != acknowledgment.identity.source:
        raise Conflict('cannot acknowledge this original to a different recording')
    source.acknowledge(acknowledgment)
    return acknowledgment
