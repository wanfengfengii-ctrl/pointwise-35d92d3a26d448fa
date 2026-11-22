from copy import deepcopy
from decimal import localcontext

from station import CaptureFailed, Conflict, InvalidInput, LostReply, NotFound
from station.capture.storage import get_original, list_shift_originals
from tests.support import StationCase


class CaptureTests(StationCase):
    def test_intake_replay_preserves_original_and_provenance(self):
        first, = self.capture(self.r)
        replay, = self.capture(self.r)
        self.assertEqual(first, replay)
        self.assertEqual(first.identity.source, self.source)
        with self.station.operations() as conn:
            saved = get_original(conn, first.original_id)
            self.assertEqual(list_shift_originals(conn, self.shift), (saved,))
        self.assertEqual(saved.value_ug_l, 7)
        self.assertEqual(saved.provenance.position, 1)
        self.assertEqual(saved.provenance.original_no, 'r')
        self.assertEqual(saved.provenance.raw_value, '0.007')
        self.assertEqual(saved.provenance.raw_unit, 'mg/L')
        self.assertEqual(saved.provenance.sampled_at, '2026-06-15T18:00:00+08:00')
        changed = self.device(dict(self.r, value='0.008'))
        with self.assertRaises(Conflict):
            self.station.capture_readings(self.shift, changed)
        self.assertFalse(changed.acknowledgments)

    def test_revision_binding_and_original_shift_on_replay(self):
        self.assertEqual(self.station.register_protocol(self.revision, deepcopy(self.projects)), self.revision)
        conflicting = deepcopy(self.projects)
        conflicting['low']['max'] = '0.006'
        with self.assertRaises(Conflict):
            self.station.register_protocol(self.revision, conflicting)
        invalid = deepcopy(self.projects)
        invalid['regular']['min'] = 26
        with self.assertRaises(InvalidInput):
            self.station.register_protocol('invalid', invalid)
        with self.assertRaises(NotFound):
            self.station.open_shift('unknown', self.site, 'missing')
        with self.assertRaises(Conflict):
            self.station.open_shift(self.shift, 'another-site', self.revision)
        first, = self.capture(self.r)
        newer = self.new_revision()
        self.station.open_shift('second', self.site, newer)
        replay, = self.station.capture_readings('second', self.device(self.r))
        self.assertEqual(replay, first)
        self.assertEqual(replay.shift_id, self.shift)
        self.assertEqual(self.station.open_shift(self.shift, self.site, self.revision).revision_id, 'P1')
        with self.station.operations() as conn:
            self.assertEqual(list_shift_originals(conn, 'second'), ())

    def test_same_number_in_two_recordings(self):
        first_raw = dict(self.r, original_no='17')
        second_raw = dict(self.s, original_no='17', position=1)
        first, = self.capture(first_raw, source='D1')
        second, = self.capture(second_raw, source='D2')
        self.assertNotEqual(first.original_id, second.original_id)
        self.assertEqual(self.capture(first_raw, source='D1'), (first,))
        self.assertEqual(self.capture(second_raw, source='D2'), (second,))
        with self.station.operations() as conn:
            originals = list_shift_originals(conn, self.shift)
        self.assertEqual([(item.provenance.source, item.value_ug_l) for item in originals], [('D1', 7), ('D2', 11)])

    def test_device_order(self):
        device = self.device(self.s, self.r)
        result = self.station.capture_readings(self.shift, device)
        self.assertEqual([ack.identity.original_no for ack in result], ['r', 's'])
        self.assertEqual(device.acknowledgments, result)
        self.assertEqual(device.read_pending(), ())
        wrong = self.device(self.r, source='other')
        with self.assertRaises(Conflict):
            wrong.acknowledge(result[0])
        self.assertEqual(wrong.read_pending(), (self.r,))

    def test_persist_before_acknowledgment(self):
        device = self.device(self.r)
        with self.assertRaises(CaptureFailed):
            self.station.capture_readings(
                self.shift, device,
                checkpoint=self.at('before_capture_commit', CaptureFailed('storage interrupted')),
            )
        self.assertEqual(device.read_pending(), (self.r,))
        self.assertEqual(device.acknowledgments, ())
        reopened = self.reopen()
        with reopened.operations() as conn:
            self.assertEqual(list_shift_originals(conn, self.shift), ())
        with self.assertRaises(LostReply):
            reopened.capture_readings(
                self.shift, device, checkpoint=self.at('after_capture_commit', LostReply('capture acknowledgment lost'))
            )
        self.assertEqual(device.read_pending(), (self.r,))
        with reopened.operations() as conn:
            original, = list_shift_originals(conn, self.shift)
        confirmed, = self.reopen().capture_readings(self.shift, device)
        self.assertEqual(confirmed.original_id, original.original_id)
        self.assertEqual(confirmed.token, original.acknowledgment_token)
        self.assertEqual(device.acknowledgments, (confirmed,))
        self.assertEqual(device.read_pending(), ())

    def test_unknown_unit(self):
        self._assert_unconfirmed(dict(self.r, unit='ppm'))

    def test_bad_quality_and_invalid_provenance(self):
        for changes in ({'quality': 'unknown'}, {'site': ''}, {'sampled_at': '2026-06-15T10:00:00'}):
            with self.subTest(changes=changes):
                self._assert_unconfirmed(dict(self.r, **changes))

    def test_inexact_conversion(self):
        self._assert_unconfirmed(dict(self.r, value='0.0079'))
        with localcontext() as context:
            context.prec = 1
            accepted, = self.capture(self.r)
        with self.station.operations() as conn:
            self.assertEqual(get_original(conn, accepted.original_id).value_ug_l, 7)

    def _assert_unconfirmed(self, raw):
        device = self.device(raw)
        with self.assertRaises(InvalidInput):
            self.station.capture_readings(self.shift, device)
        self.assertEqual(device.acknowledgments, ())
        self.assertEqual(device.read_pending(), (raw,))
        with self.station.operations() as conn:
            self.assertEqual(list_shift_originals(conn, self.shift), ())
