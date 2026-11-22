from ratings.ledger import load_signed_report


def read_report(db, report_id):
    return load_signed_report(db, report_id)
