from station import Conflict, LostReply, Pending
from station.allocation.shifts import get_shift
from station.capture.storage import list_shift_originals
from tests.support import StationCase


class ShiftAccountTests(StationCase):
    def test_unfinished_shift_remains_open(self):
        self.capture(self.r)
        self.admit('A')
        self._assert_unclosed()
        self.seal('A')
        self.assertEqual(self.station.close_and_read_shift(self.shift).totals.ticket_count, 1)

    def test_partial_closure_checks_the_whole_roster(self):
        self.prepare_pair()
        self.seal('A')
        self._assert_unclosed()
        self.seal('B')
        self.assertEqual([row.ticket_id for row in self.station.close_and_read_shift(self.shift).lines], ['A', 'B'])

    def test_successful_but_unsettled_publication_delays_closure(self):
        self.capture(self.r)
        self.admit('A')
        with self.assertRaises(LostReply):
            self.seal('A', checkpoint=self.at('after_archive_commit', LostReply('reply lost')))
        self.assertIsNotNone(self.station.read_report(request_id='qA'))
        self._assert_unclosed()
        reopened = self.reopen()
        outcome = reopened.reconcile_publication('qA')
        account = reopened.close_and_read_shift(self.shift)
        self.assertEqual(account.lines[0].receipt_id, outcome.publication.receipt.receipt_id)

    def test_history_lookup_reverse_order_and_setup_twice(self):
        r, s = self.prepare_pair()
        b = self.seal('B')
        a = self.seal('A')
        account = self.station.close_and_read_shift(self.shift)
        self.assertEqual(account.revision_id, 'P1')
        self.assertEqual([(row.ordinal, row.ticket_id, row.original_id, row.value_ug_l) for row in account.lines],
                         [(1, 'A', s.original_id, 11), (2, 'B', r.original_id, 7)])
        self.assertEqual([(row.provenance.original_no, row.provenance.position) for row in account.lines],
                         [('s', 2), ('r', 1)])
        self.assertEqual([row.receipt_id for row in account.lines], [a.receipt.receipt_id, b.receipt.receipt_id])
        self.assertEqual([row.report_id for row in account.lines], [a.report.report_id, b.report.report_id])
        self.assertEqual((account.totals.ticket_count, account.totals.publication_count,
                          account.totals.distinct_original_count, account.totals.duplicate_original_ids),
                         (2, 2, 2, ()))
        self.assertEqual(self.new_revision('user-revision'), 'user-revision')
        station = self.reopen()
        station = self.reopen()
        self.assertEqual(station.close_and_read_shift(self.shift), account)
        for pair in (a, b):
            report = pair.report
            self.assertEqual(station.read_report(report_id=report.report_id), pair)
            self.assertEqual(station.read_report(request_id=report.request_id), pair)
            self.assertEqual(station.seal_ticket(report.request_id, self.shift, report.ticket_id), pair)
        self.assertEqual(station.open_shift('user-shift', self.site, 'user-revision').revision_id, 'user-revision')
        with station.operations() as conn:
            self.assertEqual(len(list_shift_originals(conn, self.shift)), 2)
            self.assertTrue(get_shift(conn, self.shift).closed)
        with self.assertRaises(Conflict):
            station.admit_ticket(self.shift, 'late', 'regular')
        late_device = self.device(dict(self.s, original_no='late', position=3))
        with self.assertRaises(Conflict):
            station.capture_readings(self.shift, late_device)
        self.assertEqual(late_device.acknowledgments, ())

    def _assert_unclosed(self):
        with self.assertRaises(Pending):
            self.reopen().close_and_read_shift(self.shift)
        with self.station.operations() as conn:
            self.assertFalse(get_shift(conn, self.shift).closed)
            self.assertEqual(conn.execute('SELECT count(*) FROM shift_accounts').fetchone()[0], 0)
