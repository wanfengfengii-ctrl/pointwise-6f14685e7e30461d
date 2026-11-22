from dataclasses import dataclass
from fractions import Fraction

from quality.roster import FrozenRow
from ratings.brier import PieceScore
from weldbook import decode_fraction, encode_fraction, integer, read_snapshot, write_transaction


@dataclass(frozen=True)
class IssueReceipt:
    report_id: int
    receipt_id: str


@dataclass(frozen=True)
class SignedReport:
    report_id: int
    batch_id: str
    training_ids: tuple[str, str]
    scores: tuple[PieceScore, ...]
    mean_difference: Fraction | None
    receipt: IssueReceipt


def _stored_score(report_id, score):
    row = score.row
    return (
        report_id, row.position, row.piece_id, row.scan_id, row.actual,
        encode_fraction(row.first), encode_fraction(row.second), encode_fraction(score.first_error),
        encode_fraction(score.second_error), encode_fraction(score.difference),
    )


def commit_report(db, batch, scores, difference):
    with write_transaction(db):
        cursor = db.execute(
            'INSERT INTO signed_reports (batch_id, first_training, second_training, mean_difference) VALUES (?, ?, ?, ?)',
            (batch.batch_id, *batch.training_ids, None if difference is None else encode_fraction(difference)),
        )
        report_id = cursor.lastrowid
        db.executemany(
            'INSERT INTO report_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (_stored_score(report_id, score) for score in scores),
        )
        receipt = IssueReceipt(report_id, f'issue-{report_id}')
        db.execute('INSERT INTO issue_receipts VALUES (?, ?)', (report_id, receipt.receipt_id))
    return SignedReport(report_id, batch.batch_id, batch.training_ids, scores, difference, receipt)


def _loaded_score(record):
    position, piece, scan, actual, first, second, first_error, second_error, difference = record
    row = FrozenRow(position, piece, scan, actual, decode_fraction(first), decode_fraction(second))
    return PieceScore(row, decode_fraction(first_error), decode_fraction(second_error), decode_fraction(difference))


def load_signed_report(db, report_id):
    integer(report_id, 'report id')
    if report_id < 1:
        raise ValueError('report id must be positive')
    with read_snapshot(db):
        head = db.execute(
            'SELECT batch_id, first_training, second_training, mean_difference, receipt_id '
            'FROM signed_reports JOIN issue_receipts USING (report_id) WHERE report_id = ?',
            (report_id,),
        ).fetchone()
        if head is None:
            raise KeyError(report_id)
        batch_id, first, second, difference, receipt_id = head
        scores = tuple(_loaded_score(record) for record in db.execute(
            'SELECT position, piece_id, scan_id, actual, first_p, second_p, first_error, second_error, difference '
            'FROM report_rows WHERE report_id = ? ORDER BY position', (report_id,)
        ))
    return SignedReport(
        report_id, batch_id, (first, second), scores,
        None if difference is None else decode_fraction(difference), IssueReceipt(report_id, receipt_id),
    )
