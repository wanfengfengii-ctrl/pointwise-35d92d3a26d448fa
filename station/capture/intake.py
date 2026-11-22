from station.allocation.shifts import get_shift
from station.capture.acknowledgment import confirm_source_release
from station.capture.recording import read_device_order
from station.capture.storage import find_captured_source, require_same_original, store_original
from station.database import Conflict, require_name, run_checkpoint


def capture_readings(store, shift_id, source, *, checkpoint=None):
    shift_id = require_name(shift_id, 'shift_id')
    acknowledgments = []
    for recorded in read_device_order(source.source_id, source.read_pending()):
        with store.operations(write=True) as conn:
            previous = find_captured_source(conn, recorded.provenance.identity)
            if previous is None:
                shift = get_shift(conn, shift_id)
                if shift.closed:
                    raise Conflict(f'shift {shift_id} is closed to capture')
                stored = store_original(conn, shift_id, recorded)
                run_checkpoint(checkpoint, 'before_capture_commit')
            else:
                stored = require_same_original(previous, recorded)
        run_checkpoint(checkpoint, 'after_capture_commit')
        acknowledgments.append(confirm_source_release(source, stored))
    return tuple(acknowledgments)
