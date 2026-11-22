from dataclasses import dataclass

from weldbook import identifier, integer, require_transaction


@dataclass(frozen=True, order=True)
class PayloadRef:
    kind: str
    key: str

    def __post_init__(self):
        if self.kind not in ('scan', 'patch'):
            raise ValueError('payload kind must be scan or patch')
        identifier(self.key, 'payload key')


@dataclass(frozen=True)
class PayloadStatus:
    ref: PayloadRef
    expires_at: int
    available: bool


def _key(ref):
    if not isinstance(ref, PayloadRef):
        raise ValueError('expected PayloadRef')
    return ref.kind, ref.key


def store_payload(db, ref, pixels, expires_at):
    require_transaction(db)
    kind, key = _key(ref)
    integer(expires_at, 'payload expiry')
    if type(pixels) is not bytes or not pixels:
        raise ValueError('payload must be nonempty bytes')
    if db.execute(
        'SELECT 1 FROM payloads WHERE kind = ? AND target_key = ?', (kind, key)
    ).fetchone():
        raise ValueError(f'payload already registered: {ref}')
    db.execute('INSERT INTO payloads VALUES (?, ?, ?, ?)', (kind, key, expires_at, pixels))


def read_payload(db, ref):
    row = db.execute(
        'SELECT pixels FROM payloads WHERE kind = ? AND target_key = ?', _key(ref)
    ).fetchone()
    if row is None:
        raise KeyError(ref)
    if row[0] is None:
        raise ValueError(f'payload retired: {ref}')
    return row[0]


def read_payload_status(db, ref):
    row = db.execute(
        'SELECT expires_at, pixels IS NOT NULL FROM payloads WHERE kind = ? AND target_key = ?',
        _key(ref),
    ).fetchone()
    if row is None:
        raise KeyError(ref)
    return PayloadStatus(ref, row[0], bool(row[1]))


def list_due_payloads(db, cutoff):
    integer(cutoff, 'cutoff')
    return tuple(PayloadRef(*row) for row in db.execute(
        'SELECT kind, target_key FROM payloads WHERE expires_at <= ? AND pixels IS NOT NULL '
        'ORDER BY kind, target_key', (cutoff,)
    ))


def discard_payload(db, ref, cutoff):
    require_transaction(db)
    integer(cutoff, 'cutoff')
    status = read_payload_status(db, ref)
    if not status.available or status.expires_at > cutoff:
        raise ValueError(f'payload cannot be retired at {cutoff}: {ref}')
    db.execute('UPDATE payloads SET pixels = NULL WHERE kind = ? AND target_key = ?', _key(ref))
