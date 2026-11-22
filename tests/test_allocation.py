from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier

from station import NotFound, Unavailable
from station.allocation.commitments import load_shift_commitments
from station.capture.storage import get_original
from station.protocol.eligibility import eligible_projects
from station.protocol.revisions import get_protocol_revision
from tests.support import StationCase


class AllocationTests(StationCase):
    def test_preview_then_later_admission(self):
        r, = self.capture(self.r)
        self.admit('A')
        preview = self.station.preview_ticket(self.shift, 'A')
        self.assertEqual([item.original_id for item in preview.candidates], [r.original_id])
        with self.station.operations() as conn:
            self.assertEqual(load_shift_commitments(conn, self.shift).claims, ())
        s, = self.capture(self.s)
        b_ticket = self.admit('B', 'low')
        self.assertEqual(b_ticket.ordinal, 2)
        a = self.seal('A')
        b = self.seal('B')
        self.assertEqual((a.report.original_id, a.report.value_ug_l), (s.original_id, 11))
        self.assertEqual((b.report.original_id, b.report.value_ug_l), (r.original_id, 7))
        self.assertEqual((a.report.provenance.original_no, b.report.provenance.original_no), ('s', 'r'))
        self.assertEqual((a.report.provenance.position, b.report.provenance.position), (2, 1))
        self.assertEqual((a.report.provenance.source, b.report.provenance.source), (self.source, self.source))
        self.assertNotEqual(a.receipt, b.receipt)
        reloaded = self.reopen()
        account = reloaded.close_and_read_shift(self.shift)
        self.assertEqual([(row.ticket_id, row.value_ug_l, row.receipt_id) for row in account.lines],
                         [('A', 11, a.receipt.receipt_id), ('B', 7, b.receipt.receipt_id)])
        self.assertEqual(account.totals.distinct_original_count, 2)
        self.assertEqual(reloaded.read_report(report_id=a.report.report_id), a)
        self.assertEqual(reloaded.read_report(request_id='qB'), b)

    def test_mirrored_candidates(self):
        projects = deepcopy(self.projects)
        projects['high'] = dict(projects['regular'], min=11)
        self.station.register_protocol('mirror', projects)
        self.station.open_shift('mirror', self.site, 'mirror')
        r, s = self.station.capture_readings('mirror', self.device(self.s, self.r))
        self.station.admit_ticket('mirror', 'A', 'regular')
        self.station.admit_ticket('mirror', 'B', 'high')
        a = self.station.seal_ticket('mirror-a', 'mirror', 'A')
        b = self.station.seal_ticket('mirror-b', 'mirror', 'B')
        self.assertEqual((a.report.original_id, b.report.original_id), (r.original_id, s.original_id))
        self.assertEqual((a.report.value_ug_l, b.report.value_ug_l), (7, 11))

    def test_upper_endpoint(self):
        r, = self.capture(self.r)
        with self.station.operations() as conn:
            revision = get_protocol_revision(conn, self.revision)
            self.assertEqual(eligible_projects(revision, get_original(conn, r.original_id), self.site), ('low', 'regular'))
        self.admit('B', 'low')
        self.assertEqual(self.seal('B').report.original_id, r.original_id)

    def test_sampling_boundaries(self):
        rows = [self.r]
        variations = [
            ('end', {}),
            ('later', {'sampled_at': '2026-06-15T10:15:00.000001Z'}),
            ('earlier', {'sampled_at': '2026-06-15T09:59:59.999999Z'}),
            ('wrong-site', {'site': 'south-inlet'}),
            ('review', {'quality': 'review'}),
        ]
        for position, (number, changes) in enumerate(variations, start=2):
            row = dict(self.r, original_no=number, position=position, sampled_at='2026-06-15T10:15:00Z')
            row.update(changes)
            rows.append(row)
        self.assertEqual(len(self.capture(*rows)), 6)
        self.admit('A')
        preview = self.station.preview_ticket(self.shift, 'A')
        self.assertEqual([item.provenance.original_no for item in preview.candidates], ['r', 'end'])
        self.admit('B', 'low', start='2026-06-15T10:15:00Z', end='2026-06-15T10:15:00Z')
        self.assertEqual(self.seal('A').report.provenance.original_no, 'r')
        self.assertEqual(self.seal('B').report.provenance.original_no, 'end')
        self.assertEqual(self.station.preview_ticket(self.shift, 'A').candidates, ())
        with self.assertRaises(NotFound):
            self.station.preview_ticket(self.shift, 'unknown')

    def test_two_tickets_cannot_share_only_original(self):
        self.capture(self.r)
        first = self.admit('A', 'low')
        self.assertEqual(self.admit('A', 'low'), first)
        with self.assertRaises(Unavailable):
            self.admit('B', 'low')
        with self.station.operations() as conn:
            self.assertEqual(load_shift_commitments(conn, self.shift).tickets, (first,))

    def test_sign_before_admission(self):
        r, = self.capture(self.r)
        self.admit('A')
        self.assertEqual(self.seal('A').report.original_id, r.original_id)
        with self.assertRaises(Unavailable):
            self.reopen().admit_ticket(self.shift, 'B', 'low')
        self.assertEqual(self.station.close_and_read_shift(self.shift).totals.ticket_count, 1)

    def test_competing_admissions_have_only_one_winner(self):
        self.capture(self.r)
        ready = Barrier(2, timeout=10)

        def admit_competitor(ticket):
            station = self.reopen()
            ready.wait()
            try:
                return station.admit_ticket(self.shift, ticket, 'low').ticket_id
            except Unavailable:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(pool.map(admit_competitor, ('A', 'B')))
        winners = tuple(ticket for ticket in results if ticket is not None)
        self.assertEqual(len(winners), 1)
        with self.station.operations() as conn:
            tickets = load_shift_commitments(conn, self.shift).tickets
        self.assertEqual([(ticket.ticket_id, ticket.ordinal) for ticket in tickets], [(winners[0], 1)])
        self.assertEqual(self.seal(winners[0]).report.value_ug_l, 7)
