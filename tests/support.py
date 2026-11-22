from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from station import Station
from station.capture.recording import DeviceRecording


class StationCase(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='station-test-')
        self.addCleanup(temporary.cleanup)
        self.directory = temporary.name
        data_path = Path(__file__).resolve().parents[1] / 'samples' / 'day.json'
        data = json.loads(data_path.read_text(encoding='utf-8'))
        self.projects = data['projects']
        self.r, self.s = data['readings']
        self.shift = data['shift']
        self.site = data['site']
        self.revision = data['revision']
        self.source = data['source']
        self.station = self.reopen()
        self.station.register_protocol(self.revision, self.projects)
        self.station.open_shift(self.shift, self.site, self.revision)

    def reopen(self):
        return Station(self.directory)

    def device(self, *rows, source=None):
        return DeviceRecording(self.source if source is None else source, rows)

    def capture(self, *rows, source=None):
        equipment = self.device(*rows, source=source)
        return self.station.capture_readings(self.shift, equipment)

    def admit(self, ticket, project='regular', **window):
        return self.station.admit_ticket(self.shift, ticket, project, **window)

    def seal(self, ticket, request=None, **options):
        return self.station.seal_ticket('q' + ticket if request is None else request, self.shift, ticket, **options)

    def prepare_pair(self):
        r, s = self.capture(self.r, self.s)
        self.admit('A')
        self.admit('B', 'low')
        return r, s

    def new_revision(self, name='P2', upper=3):
        changed = deepcopy(self.projects)
        changed['regular']['max'] = upper
        return self.station.register_protocol(name, changed)

    @staticmethod
    def at(stage, exception):
        def checkpoint(actual):
            if actual == stage:
                raise exception
        return checkpoint
