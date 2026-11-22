from dataclasses import dataclass

from weldbook import identifier, require_transaction


@dataclass(frozen=True, order=True)
class HoldTarget:
    kind: str
    key: str

    def __post_init__(self):
        if self.kind not in ('scan', 'patch', 'definition'):
            raise ValueError('hold kind must be scan, patch or definition')
        identifier(self.key, 'hold key')


def hold_materials(db, training_id, targets):
    require_transaction(db)
    db.executemany(
        'INSERT INTO material_holds VALUES (?, ?, ?)',
        ((target.kind, target.key, training_id) for target in targets),
    )


def release_order_holds(db, training_id):
    require_transaction(db)
    db.execute('DELETE FROM material_holds WHERE training_id = ?', (training_id,))


def active_holders(db, target):
    if not isinstance(target, HoldTarget):
        raise ValueError('expected HoldTarget')
    return tuple(row[0] for row in db.execute(
        'SELECT training_id FROM material_holds WHERE kind = ? AND target_key = ? ORDER BY training_id',
        (target.kind, target.key),
    ))
