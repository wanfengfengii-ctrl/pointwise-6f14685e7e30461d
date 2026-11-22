from dataclasses import dataclass
from fractions import Fraction

from training.receipts import read_training_receipt
from weldbook import encode_fraction, keyed, pair, require_transaction


@dataclass(frozen=True)
class PredictionBatch:
    training_id: str
    values: tuple[tuple[str, Fraction], ...]


def normalize_probability(value):
    if isinstance(value, Fraction) or type(value) is int:
        probability = Fraction(value)
    else:
        numerator, denominator = pair(value, 'probability')
        if type(numerator) is not int or type(denominator) is not int or denominator <= 0:
            raise ValueError('probability requires an integer numerator and positive integer denominator')
        probability = Fraction(numerator, denominator)
    if not 0 <= probability <= 1:
        raise ValueError('probability must lie in [0, 1]')
    return probability


def build_prediction_batch(db, training_id, rows):
    read_training_receipt(db, training_id)
    return PredictionBatch(training_id, tuple(
        (piece_id, normalize_probability(value)) for piece_id, value in keyed(rows, 'prediction').items()
    ))


def store_prediction_batch(db, batch_id, position, predictions):
    require_transaction(db)
    db.execute('INSERT INTO prediction_groups VALUES (?, ?, ?)', (batch_id, position, predictions.training_id))
    db.executemany(
        'INSERT INTO prediction_records VALUES (?, ?, ?, ?, ?)',
        ((batch_id, position, submitted_position, piece_id, encode_fraction(value))
         for submitted_position, (piece_id, value) in enumerate(predictions.values)),
    )
