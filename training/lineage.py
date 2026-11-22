from weldbook import require_transaction


def store_revision_evidence(db, revision_id, parents):
    require_transaction(db)
    db.executemany(
        'INSERT INTO revision_parent_evidence VALUES (?, ?, ?, ?)',
        ((revision_id, position, ref.kind, ref.key) for position, ref in enumerate(parents)),
    )


def _evidence_rows(db, revision_id):
    return tuple(db.execute(
        'SELECT kind, parent_key FROM revision_parent_evidence WHERE revision_id = ? ORDER BY position',
        (revision_id,),
    ))


def _production_rows(db, revision_id):
    return tuple(db.execute(
        'SELECT kind, parent_key FROM patch_parents WHERE revision_id = ? ORDER BY position',
        (revision_id,),
    ))


def revision_scan_ancestry(db, revision_id):
    """Return the deduplicated original scans behind a patch revision.

    The retained evidence table keeps every parent link after a superseded
    definition is retired. Ledgers initialized before the evidence table
    existed fall back to the V1 production parent table; a missing link makes
    the lineage incomplete and the result is None.
    """
    legacy = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'revision_parent_evidence'"
    ).fetchone() is None
    pending = [revision_id]
    seen = set()
    scans = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if legacy:
            rows = _production_rows(db, current)
            if not rows:
                return None
        else:
            evidence = _evidence_rows(db, current)
            if evidence:
                rows = evidence
            else:
                rows = _production_rows(db, current)
                if not rows:
                    return None
        for kind, parent_key in rows:
            if kind == 'scan':
                scans.add(parent_key)
            elif parent_key not in seen:
                pending.append(parent_key)
    return scans
