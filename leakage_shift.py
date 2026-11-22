from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from quality.freeze import freeze_test
from ratings.export import export_report
from ratings.issue import issue_report
from ratings.read import read_report
from retention.holds import HoldTarget
from retention.sweep import sweep_due
from scans.attribution import publish_attribution, read_scan_attribution
from scans.register import register_scan
from scans.seams import register_seam
from training.finish import finish_training
from training.parents import ParentRef
from training.patches import read_patch_revision, revise_patch
from training.work_orders import checkout_training_materials
from weldbook import initialize, open_ledger


ASSIGNMENTS = {
    "s1": "W1", "s2": "W2", "s3": "W3", "s4": "W4",
    "z": "W4", "y": "W4", "w": "W4",
}


def seed_shift(db):
    """Load a fresh ledger through the V1 business entries."""
    for number in range(1, 5):
        register_seam(db, f"W{number}", f"Bench {number}")
    for scan, seam in ASSIGNMENTS.items():
        register_scan(db, seam, scan, f"capture-{scan}", scan.encode(), 10)
    publish_attribution(db, "R1", ASSIGNMENTS)
    revise_patch(db, "P", "p1", [ParentRef("scan", "s1"), ParentRef("scan", "s2")], b"inner", 10)
    revise_patch(db, "M", "m1", [ParentRef("patch", "p1"), ParentRef("scan", "s1")], b"mosaic", 30)
    revise_patch(db, "B", "b1", [ParentRef("scan", "s3")], b"other", 30)
    checkout_training_materials(db, "A", [
        HoldTarget("patch", "m1"), HoldTarget("definition", "m1"), HoldTarget("patch", "b1"),
    ])
    revise_patch(db, "P", "p2", [ParentRef("scan", "s4")], b"inner-new", 50)
    retired = sweep_due(db, 10).retired
    assert HoldTarget("definition", "p1") in {item.target for item in retired}
    assert read_patch_revision(db, "m1").parents[0] == ParentRef("patch", "p1")
    assert finish_training(db, "A", ["m1"]).revision_ids == ("m1",)
    finish_training(db, "B", ["b1"])
    return freeze_test(
        db, "night", ("A", "B"), [("z", "z"), ("y", "y"), ("w", "w")],
        [("z", 0), ("y", 1), ("w", 0)], [
            ("A", [("z", 0), ("y", (1, 2)), ("w", (1, 4))]),
            ("B", [("w", (3, 4)), ("y", (1, 2)), ("z", 0)]),
        ],
    )


def retire_shift(db):
    revise_patch(db, "M", "m2", [ParentRef("scan", "s4")], b"mosaic-new", 50)
    revise_patch(db, "B", "b2", [ParentRef("scan", "s4")], b"other-new", 50)
    return sweep_due(db, 30)


def publish_review_revisions(db):
    amended = dict(ASSIGNMENTS, z="W2", y="W3")
    publish_attribution(db, "R2", amended)
    publish_attribution(db, "Rwait", {scan: seam for scan, seam in amended.items() if scan != "s2"})
    publish_attribution(db, "Rall", dict(amended, w="W1", s3="W1", y="W1"))


def main():
    with TemporaryDirectory(prefix="weldbook-lineage-") as directory:
        path = Path(directory) / "ledger.sqlite3"
        with open_ledger(path) as db:
            initialize(db)
            batch = seed_shift(db)
            report = issue_report(db, batch.batch_id)
            assert tuple(score.row.piece_id for score in report.scores) == ("z", "y", "w")
            assert report.mean_difference == Fraction(-1, 6)
            exported = export_report(db, report.report_id)
            retired = {item.target for item in retire_shift(db).retired}
            assert {HoldTarget("definition", "m1"), HoldTarget("definition", "b1")} <= retired
        with open_ledger(path) as db:
            publish_review_revisions(db)
            assert read_scan_attribution(db, "R2", "z") == "W2"
            assert read_report(db, report.report_id) == report
            assert export_report(db, report.report_id) == exported
    print(exported)


if __name__ == "__main__":
    main()
