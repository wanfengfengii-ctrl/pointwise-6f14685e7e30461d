from dataclasses import dataclass

from scans.read import read_scan
from scans.seams import get_seam
from weldbook import identifier, keyed, read_snapshot, write_transaction


@dataclass(frozen=True)
class AttributionRevision:
    revision_id: str
    assignments: tuple[tuple[str, str], ...]


def publish_attribution(db, revision_id, assignments):
    identifier(revision_id, 'attribution revision')
    entries = tuple(sorted(keyed(assignments, 'scan attribution').items()))
    with write_transaction(db):
        if db.execute(
            'SELECT 1 FROM attribution_revisions WHERE revision_id = ?', (revision_id,)
        ).fetchone():
            raise ValueError(f'attribution revision already exists: {revision_id}')
        for scan_id, seam_id in entries:
            read_scan(db, scan_id)
            get_seam(db, seam_id)
        db.execute('INSERT INTO attribution_revisions VALUES (?)', (revision_id,))
        db.executemany(
            'INSERT INTO scan_attributions VALUES (?, ?, ?)',
            ((revision_id, scan_id, seam_id) for scan_id, seam_id in entries),
        )
    return AttributionRevision(revision_id, entries)


def read_scan_attribution(db, revision_id, scan_id):
    identifier(revision_id, 'attribution revision')
    with read_snapshot(db):
        read_scan(db, scan_id)
        if db.execute(
            'SELECT 1 FROM attribution_revisions WHERE revision_id = ?', (revision_id,)
        ).fetchone() is None:
            raise KeyError(revision_id)
        row = db.execute(
            'SELECT seam_id FROM scan_attributions WHERE revision_id = ? AND scan_id = ?',
            (revision_id, scan_id),
        ).fetchone()
    return None if row is None else row[0]
