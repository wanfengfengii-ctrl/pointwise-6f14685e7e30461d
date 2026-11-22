from dataclasses import dataclass

from retention.holds import HoldTarget
from training.patches import list_superseded_definitions, retire_patch_definition
from weldbook import integer, require_transaction


@dataclass(frozen=True)
class RetirementReceipt:
    target: HoldTarget
    cutoff: int


def list_due_definitions(db, cutoff):
    return tuple(HoldTarget('definition', revision) for revision in list_superseded_definitions(db, cutoff))


def retire_definition(db, target, cutoff):
    if not isinstance(target, HoldTarget) or target.kind != 'definition':
        raise ValueError('expected a definition hold target')
    retire_patch_definition(db, target.key, cutoff)


def record_retirement(db, target, cutoff):
    require_transaction(db)
    integer(cutoff, 'cutoff')
    db.execute('INSERT INTO retirement_receipts VALUES (?, ?, ?)', (target.kind, target.key, cutoff))
    return RetirementReceipt(target, cutoff)


def read_retirement_receipt(db, target):
    if not isinstance(target, HoldTarget):
        raise ValueError('expected HoldTarget')
    row = db.execute(
        'SELECT cutoff FROM retirement_receipts WHERE kind = ? AND target_key = ?', (target.kind, target.key)
    ).fetchone()
    if row is None:
        raise KeyError(target)
    return RetirementReceipt(target, row[0])
