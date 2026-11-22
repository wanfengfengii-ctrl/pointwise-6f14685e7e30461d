from dataclasses import dataclass

from retention.eligibility import ProtectedItem, plan_due_items
from retention.payloads import PayloadRef, discard_payload
from retention.retire import RetirementReceipt, record_retirement, retire_definition
from weldbook import integer, write_transaction


@dataclass(frozen=True)
class SweepResult:
    cutoff: int
    retired: tuple[RetirementReceipt, ...]
    protected: tuple[ProtectedItem, ...]


def sweep_due(db, cutoff):
    integer(cutoff, 'cutoff')
    with write_transaction(db):
        plan = plan_due_items(db, cutoff)
        retired = []
        for target in plan.eligible:
            if target.kind == 'definition':
                retire_definition(db, target, cutoff)
            else:
                discard_payload(db, PayloadRef(target.kind, target.key), cutoff)
            retired.append(record_retirement(db, target, cutoff))
    return SweepResult(cutoff, tuple(retired), plan.protected)
