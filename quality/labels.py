from dataclasses import dataclass

from weldbook import keyed, require_transaction


@dataclass(frozen=True)
class LabelSheet:
    values: tuple[tuple[str, int], ...]


def build_label_sheet(rows):
    labels = keyed(rows, 'label')
    for piece_id, actual in labels.items():
        if type(actual) is not int or actual not in (0, 1):
            raise ValueError(f'label must be integer zero or one: {piece_id}')
    return LabelSheet(tuple(labels.items()))


def store_label_sheet(db, batch_id, sheet):
    require_transaction(db)
    db.executemany(
        'INSERT INTO label_records VALUES (?, ?, ?)',
        ((batch_id, piece_id, actual) for piece_id, actual in sheet.values),
    )
