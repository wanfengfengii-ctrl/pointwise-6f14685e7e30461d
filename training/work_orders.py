from dataclasses import dataclass

from retention.holds import HoldTarget, hold_materials, release_order_holds
from retention.payloads import PayloadRef, read_payload_status
from scans.read import read_scan
from training.patches import read_patch_revision
from weldbook import identifier, ordered, read_snapshot, require_transaction, write_transaction


@dataclass(frozen=True)
class WorkOrder:
    training_id: str
    targets: tuple[HoldTarget, ...]
    closed: bool


def _require_available(db, target):
    if target.kind == 'definition':
        read_patch_revision(db, target.key)
        return
    if target.kind == 'scan':
        read_scan(db, target.key)
    status = read_payload_status(db, PayloadRef(target.kind, target.key))
    if not status.available:
        raise ValueError(f'checkout material retired: {target}')


def checkout_training_materials(db, training_id, targets):
    identifier(training_id, 'training id')
    targets = ordered(targets, 'checkout targets')
    if not targets or any(not isinstance(target, HoldTarget) for target in targets):
        raise ValueError('checkout requires at least one HoldTarget')
    if len(set(targets)) != len(targets):
        raise ValueError('duplicate checkout target')
    with write_transaction(db):
        if db.execute(
            'SELECT 1 FROM work_orders WHERE training_id = ? UNION ALL '
            'SELECT 1 FROM training_receipts WHERE training_id = ?', (training_id, training_id)
        ).fetchone():
            raise ValueError(f'training id already used: {training_id}')
        for target in targets:
            _require_available(db, target)
        db.execute('INSERT INTO work_orders (training_id) VALUES (?)', (training_id,))
        db.executemany(
            'INSERT INTO work_order_materials VALUES (?, ?, ?, ?)',
            ((training_id, position, target.kind, target.key) for position, target in enumerate(targets)),
        )
        hold_materials(db, training_id, targets)
    return WorkOrder(training_id, targets, False)


def read_work_order(db, training_id):
    identifier(training_id, 'training id')
    with read_snapshot(db):
        row = db.execute('SELECT closed FROM work_orders WHERE training_id = ?', (training_id,)).fetchone()
        if row is None:
            raise KeyError(training_id)
        targets = tuple(HoldTarget(*material) for material in db.execute(
            'SELECT kind, target_key FROM work_order_materials WHERE training_id = ? ORDER BY position',
            (training_id,),
        ))
    return WorkOrder(training_id, targets, bool(row[0]))


def close_work_order(db, training_id):
    require_transaction(db)
    order = read_work_order(db, training_id)
    if order.closed:
        raise ValueError(f'work order already closed: {training_id}')
    db.execute('UPDATE work_orders SET closed = 1 WHERE training_id = ?', (training_id,))
    release_order_holds(db, training_id)
