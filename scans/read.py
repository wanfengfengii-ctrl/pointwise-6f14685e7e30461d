from dataclasses import dataclass

from retention.payloads import PayloadRef
from weldbook import identifier


@dataclass(frozen=True)
class Scan:
    scan_id: str
    capture_sheet: str
    initial_seam: str | None
    payload: PayloadRef


def read_scan(db, scan_id):
    identifier(scan_id, 'scan id')
    row = db.execute(
        'SELECT capture_sheet, initial_seam FROM scans WHERE scan_id = ?', (scan_id,)
    ).fetchone()
    if row is None:
        raise KeyError(scan_id)
    return Scan(scan_id, *row, PayloadRef('scan', scan_id))
