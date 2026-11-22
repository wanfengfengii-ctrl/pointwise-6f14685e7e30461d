import json
from pathlib import Path
from tempfile import TemporaryDirectory

from quality.freeze import freeze_test
from ratings.export import export_report
from ratings.issue import issue_report
from ratings.read import read_report
from retention.holds import HoldTarget
from retention.payloads import read_payload_status
from retention.retire import read_retirement_receipt
from retention.sweep import sweep_due
from scans.attribution import publish_attribution
from scans.read import read_scan
from scans.register import intake_unassigned_scan, register_scan
from scans.seams import register_seam
from training.finish import finish_training
from training.parents import ParentRef
from training.patches import revise_patch
from training.work_orders import checkout_training_materials
from weldbook import initialize, open_ledger, write_transaction


_SAMPLE = Path(__file__).with_name('samples') / 'shift.json'


def _add_patch(db, record):
    patch, revision, parents, pixels, expiry = record
    return revise_patch(db, patch, revision, [ParentRef(*parent) for parent in parents], pixels.encode('utf-8'), expiry)


def load_shift(db, sample):
    with write_transaction(db):
        if db.execute('SELECT 1 FROM seams UNION ALL SELECT 1 FROM scans '
                      'UNION ALL SELECT 1 FROM attribution_revisions UNION ALL SELECT 1 FROM work_orders LIMIT 1').fetchone():
            raise ValueError('sample requires a ledger with no business records')
        for seam_id, description in sample['seams']:
            register_seam(db, seam_id, description)
        for seam_id, scan_id, sheet, pixels, expiry in sample['scans']:
            data = scan_id, sheet, pixels.encode('utf-8'), expiry
            if seam_id is None:
                intake_unassigned_scan(db, *data)
            else:
                register_scan(db, seam_id, *data)
        publish_attribution(db, *sample['attribution'])
        for patch in sample['patches']:
            _add_patch(db, patch)
        order, targets = sample['checkout']
        checkout_training_materials(db, order, [HoldTarget(*target) for target in targets])
        for finish in sample['finishes']:
            finish_training(db, *finish)
        _add_patch(db, sample['replacement'])
        return freeze_test(db, sample['test_batch'], sample['training_ids'], sample['roster'], sample['labels'], sample['predictions'])


def _ratio(value):
    return [value['numerator'], value['denominator']]


def _score_view(body):
    return {
        'pieces': [row['piece_id'] for row in body['rows']],
        'actuals': [row['actual'] for row in body['rows']],
        'errors': [[_ratio(error) for error in row['errors']] for row in body['rows']],
        'differences': [_ratio(row['difference']) for row in body['rows']],
        'mean': _ratio(body['mean_difference']),
    }


def main():
    sample = json.loads(_SAMPLE.read_text(encoding='utf-8'))
    expected = {
        'pieces': ['t9', 't2'], 'actuals': [0, 1],
        'errors': [[['1', '9'], ['1', '4']], [['1', '9'], ['9', '16']]],
        'differences': [['-5', '36'], ['-65', '144']], 'mean': ['-85', '288'],
    }
    with TemporaryDirectory(prefix='weldbook-demo-') as directory:
        path = Path(directory) / 'day.sqlite3'
        with open_ledger(path) as db:
            initialize(db)
            batch = load_shift(db, sample)
            report = issue_report(db, batch.batch_id)
            export = export_report(db, report.report_id)
            actual = _score_view(json.loads(export))
            assert actual == expected, actual
            sweep_due(db, sample['cutoff'])
        with open_ledger(path) as db:
            initialize(db)
            archived = read_report(db, report.report_id)
            available = read_payload_status(db, read_scan(db, 'test-9').payload).available
            retired = read_retirement_receipt(db, HoldTarget('definition', 'mosaic-1'))
            downstream_actual = {
                'same_report': archived == report and export_report(db, report.report_id) == export,
                'test_pixels_available': available,
                'old_definition_cutoff': retired.cutoff,
            }
    downstream_expected = {'same_report': True, 'test_pixels_available': False, 'old_definition_cutoff': 20}
    assert downstream_actual == downstream_expected, downstream_actual
    print(f'Report {report.report_id} ({report.receipt.receipt_id}), mean Brier difference {report.mean_difference}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v4',
        'input': {key: sample[key] for key in ('roster', 'labels', 'predictions', 'cutoff')},
        'expected': expected, 'actual': actual,
        'downstream_expected': downstream_expected, 'downstream_actual': downstream_actual,
        'code_paths': ['quality/freeze.py', 'quality/roster.py', 'ratings/brier.py', 'ratings/ledger.py',
                       'ratings/export.py', 'retention/sweep.py'],
        'oracle': 'Hand calculation from the two labels and four rational probabilities, then equality with the issued export after reopening.',
    }, sort_keys=True, ensure_ascii=False))


if __name__ == '__main__':
    main()
