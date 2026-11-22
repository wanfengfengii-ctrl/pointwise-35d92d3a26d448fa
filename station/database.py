from contextlib import contextmanager
from pathlib import Path
import sqlite3


class StationError(Exception):
    pass


class InvalidInput(StationError):
    pass


class NotFound(StationError):
    pass


class Conflict(StationError):
    pass


class Unavailable(StationError):
    pass


class Pending(StationError):
    pass


class LostReply(Pending):
    pass


class CaptureFailed(StationError):
    pass


class SaveFailed(StationError):
    pass


class IntegrityViolation(StationError):
    pass


def require_name(value, field):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise InvalidInput(f'{field} must be a nonempty name')
    return str(value)


def run_checkpoint(checkpoint, stage):
    if checkpoint is not None:
        checkpoint(stage)


@contextmanager
def transaction(path, *, write):
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


class StationStore:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.operations_path = directory / 'operations.sqlite3'
        self.archive_path = directory / 'archive.sqlite3'

    def operations(self, *, write=False):
        return transaction(self.operations_path, write=write)

    def archive(self, *, write=False):
        return transaction(self.archive_path, write=write)
