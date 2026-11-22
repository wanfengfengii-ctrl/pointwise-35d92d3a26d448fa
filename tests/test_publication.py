from station import Conflict, LostReply, Pending, SaveFailed, Unavailable
from station.allocation.commitments import load_shift_commitments
from station.archive.retrieval import read_publication_outcome
from tests.support import StationCase


class PublicationTests(StationCase):
    def test_atomic_pair_and_rollback_release(self):
        r, = self.capture(self.r)
        self.admit('A')
        stages = []

        def fail_between_report_and_receipt(stage):
            stages.append(stage)
            if stage == 'before_receipt':
                raise SaveFailed('archive interrupted before the first receipt')

        with self.assertRaises(SaveFailed):
            self.seal('A', checkpoint=fail_between_report_and_receipt)
        self.assertEqual(stages, ['after_claim', 'before_receipt'])
        station = self.reopen()
        self.assertIsNone(station.read_report(request_id='qA'))
        self.assertIsNone(station.read_report(report_id='report:qA'))
        with station.archive() as conn:
            failed = read_publication_outcome(conn, 'qA')
            self.assertEqual((failed.state, failed.original_id), ('failed', r.original_id))
            self.assertEqual(conn.execute('SELECT count(*) FROM reports').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM first_receipts').fetchone()[0], 0)
        with station.operations() as conn:
            commitments = load_shift_commitments(conn, self.shift)
        self.assertEqual(commitments.claims, ())
        self.assertEqual([ticket.ticket_id for ticket in commitments.waiting_tickets], ['A'])
        retry = station.seal_ticket('qA', self.shift, 'A')
        self.assertEqual(retry.report.original_id, r.original_id)
        self.assertNotEqual(retry.report.attempt_id, failed.attempt_id)
        self.assertEqual(station.seal_ticket('qA', self.shift, 'A'), retry)
        totals = station.close_and_read_shift(self.shift).totals
        self.assertEqual((totals.publication_count, totals.distinct_original_count), (1, 1))
        with station.archive() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM first_receipts').fetchone()[0], 1)

    def test_reserved_unresolved_and_lost_reply(self):
        r, s = self.prepare_pair()
        with self.assertRaises(Pending):
            self.seal('A', checkpoint=self.at('after_claim', Pending('caller paused after reservation')))
        station = self.reopen()
        self.assertIsNone(station.read_report(request_id='qA'))
        with self.assertRaises(Pending):
            station.reconcile_publication('qA')
        with station.operations() as conn:
            claim, = load_shift_commitments(conn, self.shift).claims
        self.assertEqual((claim.original_id, claim.state), (s.original_id, 'pending'))
        only_s = {'start': self.s['sampled_at'], 'end': self.s['sampled_at']}
        with self.assertRaises((Pending, Unavailable)):
            station.admit_ticket(self.shift, 'C', 'regular', **only_s)
        with self.assertRaises(Pending):
            station.seal_ticket('other-a', self.shift, 'A')
        with self.assertRaises(LostReply):
            station.seal_ticket(
                'qA', self.shift, 'A',
                checkpoint=self.at('after_archive_commit', LostReply('signed reply lost')),
            )
        station = self.reopen()
        pair = station.read_report(request_id='qA')
        self.assertEqual((pair.report.original_id, pair.report.value_ug_l, pair.report.attempt_id),
                         (s.original_id, 11, claim.attempt_id))
        self.assertEqual(pair.report.provenance.original_no, 's')
        with station.operations() as conn:
            unresolved, = load_shift_commitments(conn, self.shift).claims
        self.assertEqual(unresolved, claim)
        with self.assertRaises((Pending, Unavailable)):
            station.admit_ticket(self.shift, 'C', 'regular', **only_s)
        self.assertEqual(station.seal_ticket('qA', self.shift, 'A'), pair)
        self.assertEqual(station.reconcile_publication('qA').publication, pair)
        with self.assertRaises(Conflict):
            station.seal_ticket('qA', self.shift, 'B')
        self.assertEqual(station.seal_ticket('qB', self.shift, 'B').report.original_id, r.original_id)
        account = station.close_and_read_shift(self.shift)
        self.assertEqual([row.ticket_id for row in account.lines], ['A', 'B'])
        self.assertEqual(account.lines[0].receipt_id, pair.receipt.receipt_id)
        self.assertEqual(account.totals.distinct_original_count, 2)

    def test_admission_waits_if_a_pending_attempt_could_release_its_only_edge(self):
        r, s = self.capture(self.r, self.s)
        self.admit('A')
        with self.assertRaises(Pending):
            self.seal('A', checkpoint=self.at('after_claim', Pending('outcome unknown')))
        with self.assertRaises(Pending):
            self.admit('B', 'low')
        with self.assertRaises(SaveFailed):
            self.seal('A', checkpoint=self.at('before_receipt', SaveFailed('definite failure')))
        self.assertEqual(self.admit('B', 'low').ordinal, 2)
        self.assertEqual(self.seal('A').report.original_id, s.original_id)
        self.assertEqual(self.seal('B').report.original_id, r.original_id)

    def test_delayed_writer_cannot_commit_a_fenced_attempt(self):
        r, s = self.capture(self.r, self.s)
        self.admit('A')
        retry = []

        def while_first_writer_is_paused(stage):
            if stage != 'after_claim':
                return
            station = self.reopen()
            with self.assertRaises(SaveFailed):
                station.seal_ticket('qA', self.shift, 'A', checkpoint=self.at('before_receipt', SaveFailed('rollback')))
            station.admit_ticket(self.shift, 'B', 'low')
            retry.append(station.seal_ticket('qA', self.shift, 'A'))

        with self.assertRaises(SaveFailed):
            self.seal('A', checkpoint=while_first_writer_is_paused)
        new_pair, = retry
        self.assertEqual(new_pair.report.original_id, s.original_id)
        self.assertEqual(self.reopen().read_report(request_id='qA'), new_pair)
        self.assertEqual(self.seal('B').report.original_id, r.original_id)

    def test_retired_attempt_cannot_publish_after_its_claim_is_released(self):
        r, s = self.capture(self.r, self.s)
        self.admit('A')

        def pause_first_attempt(stage):
            if stage != 'after_claim':
                return
            station = self.reopen()
            with self.assertRaises(SaveFailed):
                station.seal_ticket('qA', self.shift, 'A', checkpoint=self.at('before_receipt', SaveFailed('rollback')))
            self.assertIsNone(station.read_report(request_id='qA'))
            station.admit_ticket(self.shift, 'B', 'low')

        # The first writer resumes only after another operator retired its claim.
        with self.assertRaises(SaveFailed):
            self.seal('A', checkpoint=pause_first_attempt)
        station = self.reopen()
        self.assertIsNone(station.read_report(request_id='qA'))
        with station.operations() as conn:
            self.assertEqual(load_shift_commitments(conn, self.shift).claims, ())
        self.assertEqual(station.seal_ticket('qA', self.shift, 'A').report.original_id, s.original_id)
        self.assertEqual(station.seal_ticket('qB', self.shift, 'B').report.value_ug_l, 7)
        self.assertEqual([row.ticket_id for row in station.close_and_read_shift(self.shift).lines], ['A', 'B'])
