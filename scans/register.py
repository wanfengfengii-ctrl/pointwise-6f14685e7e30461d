from retention.payloads import PayloadRef, store_payload
from scans.read import read_scan
from scans.seams import get_seam
from weldbook import identifier, write_transaction


def _intake(db, seam_id, scan_id, capture_sheet, pixels, expires_at):
    identifier(scan_id, 'scan id')
    identifier(capture_sheet, 'capture sheet')
    with write_transaction(db):
        if seam_id is not None:
            get_seam(db, seam_id)
        if db.execute('SELECT 1 FROM scans WHERE scan_id = ?', (scan_id,)).fetchone():
            raise ValueError(f'scan already registered: {scan_id}')
        db.execute('INSERT INTO scans VALUES (?, ?, ?)', (scan_id, capture_sheet, seam_id))
        store_payload(db, PayloadRef('scan', scan_id), pixels, expires_at)
        return read_scan(db, scan_id)


def register_scan(db, seam_id, scan_id, capture_sheet, pixels, expires_at):
    identifier(seam_id, 'seam id')
    return _intake(db, seam_id, scan_id, capture_sheet, pixels, expires_at)


def intake_unassigned_scan(db, scan_id, capture_sheet, pixels, expires_at):
    return _intake(db, None, scan_id, capture_sheet, pixels, expires_at)
