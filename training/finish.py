from retention.payloads import read_payload_status
from training.patches import read_patch_revision
from training.receipts import TrainingReceipt, save_training_receipt
from training.work_orders import close_work_order, read_work_order
from weldbook import identifier, ordered, write_transaction


def finish_training(db, training_id, revision_ids):
    identifier(training_id, 'training id')
    revisions = tuple(identifier(key, 'consumed patch revision') for key in ordered(revision_ids, 'consumed revisions'))
    if not revisions or len(set(revisions)) != len(revisions):
        raise ValueError('finish requires distinct consumed revisions')
    receipt = TrainingReceipt(training_id, revisions)
    with write_transaction(db):
        if db.execute('SELECT 1 FROM training_receipts WHERE training_id = ?', (training_id,)).fetchone():
            raise ValueError(f'training already finished: {training_id}')
        try:
            order = read_work_order(db, training_id)
        except KeyError:
            order = None
        checked_out = set()
        if order is not None:
            if order.closed:
                raise ValueError(f'work order already closed: {training_id}')
            checked_out = {target.key for target in order.targets if target.kind in ('patch', 'definition')}
        for revision_id in revisions:
            revision = read_patch_revision(db, revision_id)
            if not read_payload_status(db, revision.payload).available:
                raise ValueError(f'consumed payload retired: {revision_id}')
            if order is not None and revision_id not in checked_out:
                raise ValueError(f'consumed revision was not checked out: {revision_id}')
        save_training_receipt(db, receipt)
        if order is not None:
            close_work_order(db, training_id)
    return receipt
