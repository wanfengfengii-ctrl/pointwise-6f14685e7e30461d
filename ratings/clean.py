import json
from fractions import Fraction

from quality.batches import read_frozen_batch
from ratings.brier import score_brier
from ratings.clean_ledger import CleanPieceRecord, CleanReportRecord, load_clean_report, save_clean_report
from scans.attribution import read_scan_attribution
from training.receipts import read_training_receipt, read_training_scans
from weldbook import identifier, pair, write_transaction


PENDING = {'status': 'pending'}


def issue_clean_report(db, batch_id, training_ids, attribution_id):
    identifier(batch_id, 'frozen batch id')
    ordered_pair = tuple(identifier(key, 'training id') for key in pair(training_ids, 'training pair'))
    if ordered_pair[0] == ordered_pair[1]:
        raise ValueError('comparison requires two distinct training ids')
    identifier(attribution_id, 'attribution revision')
    with write_transaction(db):
        batch = read_frozen_batch(db, batch_id)
        for training_id in ordered_pair:
            read_training_receipt(db, training_id)
        if tuple(batch.training_ids) != ordered_pair:
            raise ValueError('ordered training ids do not match the frozen batch')
        training_scans = []
        for training_id in ordered_pair:
            scans = read_training_scans(db, training_id)
            if scans is None:
                return dict(PENDING)
            training_scans.append(scans)
        roster_scans = tuple(dict.fromkeys(row.scan_id for row in batch.rows))
        seam_by_scan = {}
        for scan_id in (*roster_scans, *(scan for scans in training_scans for scan in scans)):
            seam_id = read_scan_attribution(db, attribution_id, scan_id)
            if seam_id is None:
                return dict(PENDING)
            seam_by_scan[scan_id] = seam_id
        used_seams = [
            {seam_by_scan[scan_id] for scan_id in scans}
            for scans in training_scans
        ]
        pieces = []
        differences = []
        score_by_piece = {score.row.piece_id: score for score in score_brier(batch.rows)}
        for row in batch.rows:
            matched = tuple(
                training_id
                for training_id, seams in zip(ordered_pair, used_seams)
                if seam_by_scan[row.scan_id] in seams
            )
            included = not matched
            difference = score_by_piece[row.piece_id].difference if included else None
            if included:
                differences.append(difference)
            pieces.append(CleanPieceRecord(
                row.position, row.piece_id, row.scan_id, seam_by_scan[row.scan_id], included,
                row.first, row.second, difference, matched,
            ))
        mean_difference = (
            sum(differences, Fraction(0)) / len(differences) if differences else None
        )
        record = CleanReportRecord(
            None, batch_id, ordered_pair, attribution_id,
            tuple(tuple(scans) for scans in training_scans),
            tuple(pieces), mean_difference, None,
        )
        receipt = save_clean_report(db, record)
    return load_clean_report(db, receipt.report_id)


def read_clean_report(db, report_id):
    return load_clean_report(db, report_id)


def _rational(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def export_clean_report(db, report_id):
    report = read_clean_report(db, report_id)
    body = dict(report)
    body['mean_difference'] = None if report['mean_difference'] is None else _rational(report['mean_difference'])
    return json.dumps(body, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
