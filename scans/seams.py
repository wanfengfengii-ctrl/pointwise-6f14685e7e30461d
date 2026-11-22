from dataclasses import dataclass

from weldbook import identifier, write_transaction


@dataclass(frozen=True)
class Seam:
    seam_id: str
    description: str


def register_seam(db, seam_id, description):
    identifier(seam_id, 'seam id')
    if type(description) is not str or not description.strip() or '\x00' in description:
        raise ValueError('seam description is required')
    with write_transaction(db):
        if db.execute('SELECT 1 FROM seams WHERE seam_id = ?', (seam_id,)).fetchone():
            raise ValueError(f'seam already registered: {seam_id}')
        db.execute('INSERT INTO seams VALUES (?, ?)', (seam_id, description))
    return Seam(seam_id, description)


def get_seam(db, seam_id):
    identifier(seam_id, 'seam id')
    row = db.execute('SELECT seam_id, description FROM seams WHERE seam_id = ?', (seam_id,)).fetchone()
    if row is None:
        raise KeyError(seam_id)
    return Seam(*row)
