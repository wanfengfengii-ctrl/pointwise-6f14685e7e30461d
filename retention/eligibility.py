from dataclasses import dataclass

from retention.holds import HoldTarget, active_holders
from retention.payloads import list_due_payloads
from retention.retire import list_due_definitions
from weldbook import integer, read_snapshot


@dataclass(frozen=True)
class ProtectedItem:
    target: HoldTarget
    holders: tuple[str, ...]


@dataclass(frozen=True)
class SweepPlan:
    eligible: tuple[HoldTarget, ...]
    protected: tuple[ProtectedItem, ...]


def plan_due_items(db, cutoff):
    integer(cutoff, 'cutoff')
    with read_snapshot(db):
        payloads = (HoldTarget(ref.kind, ref.key) for ref in list_due_payloads(db, cutoff))
        due = sorted((*list_due_definitions(db, cutoff), *payloads))
        eligible = []
        protected = []
        for target in due:
            holders = active_holders(db, target)
            if holders:
                protected.append(ProtectedItem(target, holders))
            else:
                eligible.append(target)
    return SweepPlan(tuple(eligible), tuple(protected))
