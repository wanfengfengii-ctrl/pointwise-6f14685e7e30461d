from dataclasses import dataclass

from retention.payloads import PayloadRef, store_payload
from training.parents import ParentRef, read_parent_refs, remove_parent_refs, store_parent_refs, validate_parents
from weldbook import identifier, integer, read_snapshot, require_transaction, write_transaction


@dataclass(frozen=True)
class PatchRevision:
    patch_id: str
    revision_id: str
    parents: tuple[ParentRef, ...]
    payload: PayloadRef
    expires_at: int
    superseded: bool


def revise_patch(db, patch_id, revision_id, parents, pixels, expires_at):
    identifier(patch_id, 'patch id')
    identifier(revision_id, 'patch revision')
    integer(expires_at, 'definition expiry')
    payload = PayloadRef('patch', revision_id)
    with write_transaction(db):
        if db.execute('SELECT 1 FROM patch_revisions WHERE revision_id = ?', (revision_id,)).fetchone():
            raise ValueError(f'patch revision already exists: {revision_id}')
        refs = validate_parents(db, parents)
        store_payload(db, payload, pixels, expires_at)
        db.execute('UPDATE patch_revisions SET superseded = 1 WHERE patch_id = ? AND superseded = 0', (patch_id,))
        db.execute(
            'INSERT INTO patch_revisions (revision_id, patch_id, expires_at) VALUES (?, ?, ?)',
            (revision_id, patch_id, expires_at),
        )
        store_parent_refs(db, revision_id, refs)
    return PatchRevision(patch_id, revision_id, refs, payload, expires_at, False)


def read_patch_revision(db, revision_id):
    identifier(revision_id, 'patch revision')
    with read_snapshot(db):
        row = db.execute(
            'SELECT patch_id, expires_at, superseded, retired FROM patch_revisions WHERE revision_id = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            raise KeyError(revision_id)
        patch_id, expires_at, superseded, retired = row
        if retired:
            raise ValueError(f'patch definition retired: {revision_id}')
        refs = read_parent_refs(db, revision_id)
    return PatchRevision(patch_id, revision_id, refs, PayloadRef('patch', revision_id), expires_at, bool(superseded))


def list_superseded_definitions(db, cutoff):
    integer(cutoff, 'cutoff')
    return tuple(row[0] for row in db.execute(
        'SELECT revision_id FROM patch_revisions '
        'WHERE superseded = 1 AND retired = 0 AND expires_at <= ? ORDER BY revision_id',
        (cutoff,),
    ))


def retire_patch_definition(db, revision_id, cutoff):
    require_transaction(db)
    integer(cutoff, 'cutoff')
    revision = read_patch_revision(db, revision_id)
    if not revision.superseded or revision.expires_at > cutoff:
        raise ValueError(f'definition cannot be retired at {cutoff}: {revision_id}')
    remove_parent_refs(db, revision_id)
    db.execute('UPDATE patch_revisions SET retired = 1 WHERE revision_id = ?', (revision_id,))
