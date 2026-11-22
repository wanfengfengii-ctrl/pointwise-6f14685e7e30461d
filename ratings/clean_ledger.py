from dataclasses import dataclass
from fractions import Fraction

from weldbook import decode_fraction, encode_fraction, integer, read_snapshot, require_transaction


@dataclass(frozen=True)
class CleanReceipt:
    report_id: int
    receipt_id: str


@dataclass(frozen=True)
class CleanPieceRecord:
    position: int
    piece_id: str
    scan_id: str
    seam_id: str
    included: bool
    first: Fraction
    second: Fraction
    difference: Fraction | None
    matched_training_ids: tuple[str, ...]


@dataclass(frozen=True)
class CleanReportRecord:
    report_id: int
    batch_id: str
    training_ids: tuple[str, str]
    attribution_id: str
    training_scans: tuple[tuple[str, ...], tuple[str, ...]]
    pieces: tuple[CleanPieceRecord, ...]
    mean_difference: Fraction | None
    receipt: CleanReceipt


def save_clean_report(db, record):
    require_transaction(db)
    cursor = db.execute(
        'INSERT INTO clean_reports '
        '(batch_id, first_training, second_training, attribution_id, mean_difference) '
        'VALUES (?, ?, ?, ?, ?)',
        (record.batch_id, *record.training_ids, record.attribution_id,
         None if record.mean_difference is None else encode_fraction(record.mean_difference)),
    )
    report_id = cursor.lastrowid
    db.executemany(
        'INSERT INTO clean_report_pieces VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        ((report_id, piece.position, piece.piece_id, piece.scan_id, piece.seam_id,
          int(piece.included), encode_fraction(piece.first), encode_fraction(piece.second),
          None if piece.difference is None else encode_fraction(piece.difference))
         for piece in record.pieces),
    )
    db.executemany(
        'INSERT INTO clean_report_matches VALUES (?, ?, ?, ?)',
        ((report_id, piece.position, model_position, training_id)
         for piece in record.pieces
         for model_position, training_id in enumerate(piece.matched_training_ids)),
    )
    for model_position, scans in enumerate(record.training_scans):
        db.executemany(
            'INSERT INTO clean_report_scans VALUES (?, ?, ?, ?)',
            ((report_id, model_position, scan_position, scan_id)
             for scan_position, scan_id in enumerate(scans)),
        )
    receipt = CleanReceipt(report_id, f'clean-{report_id}')
    db.execute('INSERT INTO clean_report_receipts VALUES (?, ?)', (report_id, receipt.receipt_id))
    return receipt


def _as_dict(record):
    included, excluded = [], []
    for piece in record.pieces:
        entry = {
            'piece_id': piece.piece_id,
            'scan_id': piece.scan_id,
            'seam_id': piece.seam_id,
            'matched_training_ids': list(piece.matched_training_ids),
        }
        (included if piece.included else excluded).append(entry)
    return {
        'status': 'signed',
        'report_id': record.report_id,
        'receipt_id': record.receipt.receipt_id,
        'batch_id': record.batch_id,
        'training_ids': list(record.training_ids),
        'attribution_id': record.attribution_id,
        'training_scans': [list(scans) for scans in record.training_scans],
        'included': included,
        'excluded': excluded,
        'mean_difference': record.mean_difference,
    }


def load_clean_report(db, report_id):
    integer(report_id, 'report id')
    if report_id < 1:
        raise ValueError('report id must be positive')
    with read_snapshot(db):
        head = db.execute(
            'SELECT batch_id, first_training, second_training, attribution_id, mean_difference, receipt_id '
            'FROM clean_reports JOIN clean_report_receipts USING (report_id) WHERE report_id = ?',
            (report_id,),
        ).fetchone()
        if head is None:
            raise KeyError(report_id)
        batch_id, first, second, attribution_id, difference, receipt_id = head
        pieces = []
        for row in db.execute(
            'SELECT position, piece_id, scan_id, seam_id, included, first_p, second_p, difference '
            'FROM clean_report_pieces WHERE report_id = ? ORDER BY position', (report_id,)
        ):
            position, piece_id, scan_id, seam_id, included, first_p, second_p, piece_difference = row
            matches = tuple(item[0] for item in db.execute(
                'SELECT training_id FROM clean_report_matches WHERE report_id = ? AND position = ? '
                'ORDER BY model_position', (report_id, position)
            ))
            pieces.append(CleanPieceRecord(
                position, piece_id, scan_id, seam_id, bool(included),
                decode_fraction(first_p), decode_fraction(second_p),
                None if piece_difference is None else decode_fraction(piece_difference), matches,
            ))
        scans = []
        for model_position in (0, 1):
            scans.append(tuple(item[0] for item in db.execute(
                'SELECT scan_id FROM clean_report_scans WHERE report_id = ? AND model_position = ? '
                'ORDER BY scan_position', (report_id, model_position)
            )))
    record = CleanReportRecord(
        report_id, batch_id, (first, second), attribution_id, (scans[0], scans[1]),
        tuple(pieces), None if difference is None else decode_fraction(difference),
        CleanReceipt(report_id, receipt_id),
    )
    return _as_dict(record)
