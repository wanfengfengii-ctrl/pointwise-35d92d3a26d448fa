import argparse
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from station import IntegrityViolation, Pending, SaveFailed, Station, Unavailable
from station.capture.recording import DeviceRecording


DATA = Path(__file__).with_name('samples') / 'day.json'


def capture(station, data, row):
    device = DeviceRecording(data['source'], [row])
    acknowledgment, = station.capture_readings(data['shift'], device)
    if device.read_pending():
        raise AssertionError('source did not release the captured original')
    return acknowledgment.original_id


def request_seal(station, shift, ticket, **options):
    try:
        station.seal_ticket('q' + ticket, shift, ticket, **options)
    except (IntegrityViolation, Pending, SaveFailed, Unavailable) as error:
        if isinstance(error.__cause__, sqlite3.Error) and not isinstance(error.__cause__, sqlite3.IntegrityError):
            raise
        return type(error).__name__
    return 'signed'


def frozen_row(station, ticket):
    pair = station.read_report(request_id='q' + ticket)
    if pair is None:
        return None
    report, receipt = pair.report, pair.receipt
    if station.read_report(report_id=report.report_id) != pair:
        raise AssertionError('request and report lookup disagree')
    source = report.provenance
    return [report.ticket_id, report.original_id, report.value_ug_l,
            source.source, source.original_no, source.position, receipt.receipt_id]


def finish(writer, directory, shift, expected):
    results = [request_seal(writer, shift, ticket) for ticket in ('A', 'B')]
    reopened = Station(directory)
    rows = [frozen_row(reopened, ticket) for ticket in ('A', 'B')]
    try:
        account = reopened.close_and_read_shift(shift)
    except (IntegrityViolation, Pending) as error:
        if isinstance(error.__cause__, sqlite3.Error) and not isinstance(error.__cause__, sqlite3.IntegrityError):
            raise
        account_rows = type(error).__name__
    else:
        account_rows = [
            [line.ticket_id, line.original_id, line.value_ug_l, line.provenance.source,
             line.provenance.original_no, line.provenance.position, line.receipt_id]
            for line in account.lines
        ]
        if account != Station(directory).close_and_read_shift(shift):
            raise AssertionError('closed shift account changed after reopening')
        if (account.totals.ticket_count, account.totals.publication_count,
                account.totals.distinct_original_count, account.totals.duplicate_original_ids) != (2, 2, 2, ()):
            raise AssertionError('wrong totals for the closed shift')
    delta = {'seals': results, 'reports': rows, 'account': account_rows, 'expected': expected}
    if results == ['signed', 'signed'] and rows == account_rows == expected:
        return 'SHIFT_HANDOFF_OK', delta, 0
    if rows[0] is not None and rows[0][4] == 'r' and results[1] == 'Unavailable' and rows[1] is None:
        return 'SHIFT_HANDOFF_WRONG_ORIGINAL', delta, 1
    return 'SHIFT_HANDOFF_INCOMPLETE', delta, 1


def delayed_writer(writer, directory, shift, expected):
    def fail_before_receipt(stage):
        if stage == 'before_receipt':
            raise SaveFailed('archive rolled back')

    def suspend_first_writer(stage):
        if stage != 'after_claim':
            return
        reopened = Station(directory)
        if request_seal(reopened, shift, 'A', checkpoint=fail_before_receipt) != 'SaveFailed':
            raise AssertionError('second operator did not observe a definite failure')
        if frozen_row(reopened, 'A') is not None:
            raise AssertionError('failed publication left a report')
        reopened.admit_ticket(shift, 'B', 'low')

    old = request_seal(writer, shift, 'A', checkpoint=suspend_first_writer)
    reopened = Station(directory)
    row = frozen_row(reopened, 'A')
    if old == 'SaveFailed' and row is None:
        return finish(reopened, directory, shift, expected)
    status = 'SHIFT_HANDOFF_RETIRED_ATTEMPT_PUBLISHED' if row is not None else 'SHIFT_HANDOFF_INCOMPLETE'
    return status, {'late_seal': old, 'late_report': row}, 1


def main():
    parser = argparse.ArgumentParser(description='Replay the shift sealing incident')
    parser.add_argument('--late', action='store_true', help='resume the failed attempt after B is admitted')
    options = parser.parse_args()
    data = json.loads(DATA.read_text(encoding='utf-8'))
    shift = data['shift']
    with TemporaryDirectory(prefix='shift-incident-') as directory:
        writer = Station(directory)
        writer.register_protocol(data['revision'], data['projects'])
        writer.open_shift(shift, data['site'], data['revision'])
        r = capture(writer, data, data['readings'][0])
        writer.admit_ticket(shift, 'A', 'regular')
        if [item.original_id for item in writer.preview_ticket(shift, 'A').candidates] != [r]:
            raise AssertionError('unexpected initial preview for A')
        s = capture(writer, data, data['readings'][1])
        expected = [['A', s, 11, data['source'], 's', 2, 'receipt:qA'],
                    ['B', r, 7, data['source'], 'r', 1, 'receipt:qB']]
        if options.late:
            status, payload, code = delayed_writer(writer, directory, shift, expected)
        else:
            writer.admit_ticket(shift, 'B', 'low')
            status, payload, code = finish(writer, directory, shift, expected)
        print(status, json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return code


if __name__ == '__main__':
    raise SystemExit(main())
