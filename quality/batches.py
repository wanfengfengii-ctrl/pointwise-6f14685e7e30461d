from dataclasses import dataclass

from quality.roster import FrozenRow
from weldbook import decode_fraction, encode_fraction, identifier, read_snapshot, require_transaction


@dataclass(frozen=True)
class FrozenBatch:
    batch_id: str
    training_ids: tuple[str, str]
    rows: tuple[FrozenRow, ...]


def save_frozen_batch(db, batch):
    require_transaction(db)
    if db.execute('SELECT 1 FROM frozen_batches WHERE batch_id = ?', (batch.batch_id,)).fetchone():
        raise ValueError(f'batch already frozen: {batch.batch_id}')
    db.execute('INSERT INTO frozen_batches VALUES (?, ?, ?)', (batch.batch_id, *batch.training_ids))
    db.executemany(
        'INSERT INTO frozen_rows VALUES (?, ?, ?, ?, ?, ?, ?)',
        ((batch.batch_id, row.position, row.piece_id, row.scan_id, row.actual,
          encode_fraction(row.first), encode_fraction(row.second)) for row in batch.rows),
    )


def read_frozen_batch(db, batch_id):
    identifier(batch_id, 'frozen batch id')
    with read_snapshot(db):
        pair = db.execute(
            'SELECT first_training, second_training FROM frozen_batches WHERE batch_id = ?', (batch_id,)
        ).fetchone()
        if pair is None:
            raise KeyError(batch_id)
        rows = tuple(
            FrozenRow(position, piece, scan, actual, decode_fraction(first), decode_fraction(second))
            for position, piece, scan, actual, first, second in db.execute(
                'SELECT position, piece_id, scan_id, actual, first_p, second_p '
                'FROM frozen_rows WHERE batch_id = ? ORDER BY position', (batch_id,)
            )
        )
    return FrozenBatch(batch_id, pair, rows)
