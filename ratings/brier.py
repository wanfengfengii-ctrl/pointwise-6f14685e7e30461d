from dataclasses import dataclass
from fractions import Fraction

from quality.roster import FrozenRow


@dataclass(frozen=True)
class PieceScore:
    row: FrozenRow
    first_error: Fraction
    second_error: Fraction
    difference: Fraction


def score_brier(rows):
    scores = []
    for row in rows:
        first_error = (row.first - row.actual) ** 2
        second_error = (row.second - row.actual) ** 2
        scores.append(PieceScore(row, first_error, second_error, first_error - second_error))
    return tuple(scores)


def mean_difference(scores):
    if not scores:
        return None
    return sum((score.difference for score in scores), Fraction(0)) / len(scores)
