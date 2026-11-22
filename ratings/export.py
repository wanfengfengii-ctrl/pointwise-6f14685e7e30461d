import json

from ratings.read import read_report
from weldbook import encode_fraction


def _rational(value):
    numerator, denominator = encode_fraction(value).split('/')
    return {'numerator': numerator, 'denominator': denominator}


def _export_score(score):
    row = score.row
    return {
        'position': row.position,
        'piece_id': row.piece_id,
        'scan_id': row.scan_id,
        'actual': row.actual,
        'probabilities': [_rational(row.first), _rational(row.second)],
        'errors': [_rational(score.first_error), _rational(score.second_error)],
        'difference': _rational(score.difference),
    }


def export_report(db, report_id):
    report = read_report(db, report_id)
    body = {
        'report_id': report.report_id,
        'batch_id': report.batch_id,
        'training_ids': list(report.training_ids),
        'receipt': {'receipt_id': report.receipt.receipt_id, 'report_id': report.receipt.report_id},
        'rows': [_export_score(score) for score in report.scores],
        'mean_difference': None if report.mean_difference is None else _rational(report.mean_difference),
    }
    return json.dumps(body, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
