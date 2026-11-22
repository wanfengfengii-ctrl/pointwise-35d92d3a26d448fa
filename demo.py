import json
from pathlib import Path
from tempfile import TemporaryDirectory

from station import Station
from station.capture.recording import DeviceRecording


def _require_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f'{label}: expected {expected!r}, got {actual!r}')


def main():
    data = json.loads((Path(__file__).parent / 'samples' / 'day.json').read_text(encoding='utf-8'))
    shift, site, revision = data['shift'], data['site'], data['revision']
    first, second = data['readings']
    with TemporaryDirectory(prefix='water-station-') as directory:
        station = Station(directory)
        station.register_protocol(revision, data['projects'])
        station.open_shift(shift, site, revision)
        first_device = DeviceRecording(data['source'], [first])
        first_ack, = station.capture_readings(shift, first_device)
        station.admit_ticket(shift, 'A', 'regular')
        preview = station.preview_ticket(shift, 'A')
        _require_equal([row.original_id for row in preview.candidates], [first_ack.original_id], 'A preview')
        second_device = DeviceRecording(data['source'], [second])
        second_ack, = station.capture_readings(shift, second_device)
        station.admit_ticket(shift, 'B', 'low')
        publications = [station.seal_ticket(key, shift, ticket) for key, ticket in [('qA', 'A'), ('qB', 'B')]]
        _require_equal((first_device.read_pending(), second_device.read_pending()), ((), ()), 'source release')
        del first_device, second_device
        reopened = Station(directory)
        account = reopened.close_and_read_shift(shift)
        _require_equal(Station(directory).close_and_read_shift(shift), account, 'reopened account')
        expected = [
            {'ticket': 'A', 'value_ug_l': 11, 'source': 'meter-day-export', 'original': 's', 'position': 2, 'receipt': 'receipt:qA'},
            {'ticket': 'B', 'value_ug_l': 7, 'source': 'meter-day-export', 'original': 'r', 'position': 1, 'receipt': 'receipt:qB'},
        ]
        actual = []
        for pair in publications:
            report, receipt = pair.report, pair.receipt
            _require_equal(reopened.read_report(request_id=report.request_id), pair, 'request lookup')
            _require_equal(reopened.read_report(report_id=report.report_id), pair, 'report lookup')
            actual.append({'ticket': report.ticket_id, 'value_ug_l': report.value_ug_l,
                           'source': report.provenance.source, 'original': report.provenance.original_no,
                           'position': report.provenance.position, 'receipt': receipt.receipt_id})
        _require_equal(actual, expected, 'formal publications')
        _require_equal([pair.report.original_id for pair in publications],
                       [second_ack.original_id, first_ack.original_id], 'actual capture identities')
        downstream = {'rows': [
            {'ticket': row.ticket_id, 'value_ug_l': row.value_ug_l, 'source': row.provenance.source,
             'original': row.provenance.original_no, 'position': row.provenance.position, 'receipt': row.receipt_id}
            for row in account.lines
        ], 'counts': [account.totals.ticket_count, account.totals.publication_count, account.totals.distinct_original_count]}
        downstream_expected = {'rows': expected, 'counts': [2, 2, 2]}
        _require_equal(downstream, downstream_expected, 'closed shift account')
        scenario = {
            'case_id': 'v3.formal_handoff',
            'input': {'recording': data['source'], 'readings': [first, second], 'low_upper_ug_l': 7,
                      'events': ['capture r', 'admit A', 'preview A', 'capture s', 'admit B', 'seal A', 'seal B', 'close']},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream,
            'code_paths': ['station/capture/intake.py', 'station/protocol/normalization.py',
                           'station/allocation/admission.py', 'station/allocation/settlement.py',
                           'station/archive/publication.py', 'station/audit/closing.py'],
            'oracle': '0.007 mg/L × 1000 = 7 μg/L。B 的闭上界为 7，仅 r 合格；s 为 11，故 A 必须使用 s。原录制逐行给出处，账行按 A、B 的登记顺序。',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, ensure_ascii=False))


if __name__ == '__main__':
    main()
