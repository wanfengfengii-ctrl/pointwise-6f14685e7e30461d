from dataclasses import dataclass

from weldbook import identifier, read_snapshot, require_transaction


@dataclass(frozen=True)
class TrainingReceipt:
    training_id: str
    revision_ids: tuple[str, ...]


def save_training_receipt(db, receipt):
    require_transaction(db)
    db.execute('INSERT INTO training_receipts VALUES (?)', (receipt.training_id,))
    db.executemany(
        'INSERT INTO training_inputs VALUES (?, ?, ?)',
        ((receipt.training_id, position, revision_id) for position, revision_id in enumerate(receipt.revision_ids)),
    )


def read_training_receipt(db, training_id):
    identifier(training_id, 'training id')
    with read_snapshot(db):
        if db.execute('SELECT 1 FROM training_receipts WHERE training_id = ?', (training_id,)).fetchone() is None:
            raise KeyError(training_id)
        revisions = tuple(row[0] for row in db.execute(
            'SELECT revision_id FROM training_inputs WHERE training_id = ? ORDER BY position', (training_id,)
        ))
    return TrainingReceipt(training_id, revisions)
