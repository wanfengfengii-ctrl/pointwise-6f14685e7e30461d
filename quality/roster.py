from dataclasses import dataclass
from fractions import Fraction

from scans.read import read_scan
from weldbook import keyed, ordered


@dataclass(frozen=True)
class RosterRow:
    position: int
    piece_id: str
    scan_id: str


@dataclass(frozen=True)
class FrozenRow(RosterRow):
    actual: int
    first: Fraction
    second: Fraction


def build_roster(db, rows):
    entries = keyed(ordered(rows, 'roster'), 'roster piece')
    return tuple(
        RosterRow(position, piece_id, read_scan(db, scan_id).scan_id)
        for position, (piece_id, scan_id) in enumerate(entries.items())
    )


def align_test_rows(roster, labels, first, second, training_ids):
    if (first.training_id, second.training_id) != training_ids:
        raise ValueError('prediction training ids do not match the ordered training pair')
    actual = dict(labels.values)
    first_values = dict(first.values)
    second_values = dict(second.values)
    piece_ids = {row.piece_id for row in roster}
    for role, values in (('labels', actual), ('first predictions', first_values), ('second predictions', second_values)):
        missing = sorted(piece_ids - values.keys())
        extra = sorted(values.keys() - piece_ids)
        if missing or extra:
            raise ValueError(f'{role} do not cover roster, missing={missing!r}, extra={extra!r}')
    return tuple(FrozenRow(
        row.position, row.piece_id, row.scan_id, actual[row.piece_id],
        first_values[row.piece_id], second_values[row.piece_id],
    ) for row in roster)
