from quality.batches import read_frozen_batch
from ratings.brier import mean_difference, score_brier
from ratings.ledger import commit_report


def issue_report(db, batch_id):
    batch = read_frozen_batch(db, batch_id)
    scores = score_brier(batch.rows)
    return commit_report(db, batch, scores, mean_difference(scores))
