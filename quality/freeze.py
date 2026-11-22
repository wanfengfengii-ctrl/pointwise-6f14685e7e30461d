from quality.batches import FrozenBatch, save_frozen_batch
from quality.labels import build_label_sheet, store_label_sheet
from quality.predictions import build_prediction_batch, store_prediction_batch
from quality.roster import align_test_rows, build_roster
from weldbook import identifier, pair, write_transaction


def freeze_test(db, batch_id, training_ids, roster, labels, predictions):
    identifier(batch_id, 'frozen batch id')
    training_ids = tuple(identifier(key, 'training id') for key in pair(training_ids, 'training pair'))
    if training_ids[0] == training_ids[1]:
        raise ValueError('evaluation requires two distinct training ids')
    submissions = tuple(pair(item, 'prediction submission') for item in pair(predictions, 'prediction pair'))
    label_sheet = build_label_sheet(labels)
    with write_transaction(db):
        first, second = (build_prediction_batch(db, model, rows) for model, rows in submissions)
        roster_rows = build_roster(db, roster)
        rows = align_test_rows(roster_rows, label_sheet, first, second, training_ids)
        batch = FrozenBatch(batch_id, training_ids, rows)
        save_frozen_batch(db, batch)
        store_label_sheet(db, batch_id, label_sheet)
        for position, submission in enumerate((first, second)):
            store_prediction_batch(db, batch_id, position, submission)
    return batch
