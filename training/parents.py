from dataclasses import dataclass

from scans.read import read_scan
from weldbook import identifier, ordered, read_snapshot, require_transaction


@dataclass(frozen=True)
class ParentRef:
    kind: str
    key: str

    def __post_init__(self):
        if self.kind not in ('scan', 'patch'):
            raise ValueError('parent kind must be scan or patch')
        identifier(self.key, 'parent key')


def _require_definition(db, revision_id):
    row = db.execute(
        'SELECT retired FROM patch_revisions WHERE revision_id = ?', (revision_id,)
    ).fetchone()
    if row is None:
        raise KeyError(revision_id)
    if row[0]:
        raise ValueError(f'patch definition retired: {revision_id}')


def validate_parents(db, parents):
    refs = ordered(parents, 'parents')
    if not refs or any(not isinstance(ref, ParentRef) for ref in refs):
        raise ValueError('parents must contain at least one ParentRef')
    if len(set(refs)) != len(refs):
        raise ValueError('duplicate direct parent')
    with read_snapshot(db):
        for ref in refs:
            if ref.kind == 'scan':
                read_scan(db, ref.key)
            else:
                _require_definition(db, ref.key)
    return refs


def store_parent_refs(db, revision_id, parents):
    require_transaction(db)
    db.executemany(
        'INSERT INTO patch_parents VALUES (?, ?, ?, ?)',
        ((revision_id, position, ref.kind, ref.key) for position, ref in enumerate(parents)),
    )


def read_parent_refs(db, revision_id):
    identifier(revision_id, 'patch revision')
    with read_snapshot(db):
        _require_definition(db, revision_id)
        return tuple(ParentRef(*row) for row in db.execute(
            'SELECT kind, parent_key FROM patch_parents WHERE revision_id = ? ORDER BY position',
            (revision_id,),
        ))


def remove_parent_refs(db, revision_id):
    require_transaction(db)
    db.execute('DELETE FROM patch_parents WHERE revision_id = ?', (revision_id,))
