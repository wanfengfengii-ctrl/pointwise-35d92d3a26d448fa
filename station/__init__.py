from station.allocation.admission import admit_ticket
from station.allocation.commitments import ensure_commitment_schema
from station.allocation.preview import preview_ticket
from station.allocation.shifts import ensure_shift_schema, open_shift
from station.archive.publication import (
    ensure_publication_schema,
    reconcile_publication,
    seal_ticket,
)
from station.archive.retrieval import read_report
from station.audit.closing import close_and_read_shift, ensure_account_schema
from station.capture.intake import capture_readings
from station.capture.storage import ensure_capture_schema
from station.database import (
    CaptureFailed as CaptureFailed,
    Conflict as Conflict,
    IntegrityViolation as IntegrityViolation,
    InvalidInput as InvalidInput,
    LostReply as LostReply,
    NotFound as NotFound,
    Pending as Pending,
    SaveFailed as SaveFailed,
    StationError as StationError,
    StationStore,
    Unavailable as Unavailable,
)
from station.protocol.revisions import ensure_protocol_schema, register_protocol


class Station(StationStore):
    """Public station operations bound to one persistent directory."""

    def __init__(self, directory):
        super().__init__(directory)
        with self.operations(write=True) as conn:
            ensure_protocol_schema(conn)
            ensure_shift_schema(conn)
            ensure_capture_schema(conn)
            ensure_commitment_schema(conn)
            ensure_account_schema(conn)
        with self.archive(write=True) as conn:
            ensure_publication_schema(conn)

    register_protocol = register_protocol
    open_shift = open_shift
    capture_readings = capture_readings
    admit_ticket = admit_ticket
    preview_ticket = preview_ticket
    seal_ticket = seal_ticket
    read_report = read_report
    reconcile_publication = reconcile_publication
    close_and_read_shift = close_and_read_shift
