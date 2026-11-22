from fractions import Fraction
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from quality.freeze import freeze_test
from ratings.clean import (
    export_clean_report,
    issue_clean_report,
    read_clean_report,
)
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
from training.receipts import read_training_scans
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


def _print_clean(title, report):
    included = [piece["piece_id"] for piece in report["included"]]
    excluded = [
        f'{piece["piece_id"]}->{piece["seam_id"]} 命中 {",".join(piece["matched_training_ids"])}'
        for piece in report["excluded"]
    ]
    mean = "None" if report["mean_difference"] is None else str(report["mean_difference"])
    print(f"{title}: report={report['report_id']} receipt={report['receipt_id']} "
          f"included={included} excluded=[{'; '.join(excluded)}] mean_difference={mean}")


def main():
    with TemporaryDirectory(prefix="weldbook-lineage-") as directory:
        path = Path(directory) / "ledger.sqlite3"
        with open_ledger(path) as db:
            initialize(db)
            batch = seed_shift(db)
            # Existing V1 full-roster report remains available.
            report = issue_report(db, batch.batch_id)
            assert tuple(score.row.piece_id for score in report.scores) == ("z", "y", "w")
            assert report.mean_difference == Fraction(-1, 6)
            exported = export_report(db, report.report_id)
            # New leakage-free training evidence: A only consumed m1, so b1 never counts.
            assert read_training_scans(db, "A") == ("s1", "s2")
            assert read_training_scans(db, "B") == ("s3",)
            # R1 signed before archival keeps the whole roster.
            clean_r1 = issue_clean_report(db, "night", ["A", "B"], "R1")
            assert clean_r1["mean_difference"] == Fraction(-1, 6)
            assert [piece["piece_id"] for piece in clean_r1["included"]] == ["z", "y", "w"]
            assert clean_r1["excluded"] == []
            retired = {item.target for item in retire_shift(db).retired}
            assert {HoldTarget("definition", "m1"), HoldTarget("definition", "b1")} <= retired
            # Evidence survives the cleanup of definitions and pixels.
            assert read_training_scans(db, "A") == ("s1", "s2")
            assert read_training_scans(db, "B") == ("s3",)
        with open_ledger(path) as db:
            publish_review_revisions(db)
            assert read_scan_attribution(db, "R2", "z") == "W2"
            assert read_report(db, report.report_id) == report
            assert export_report(db, report.report_id) == exported
            # Archived re-version comparison under R2.
            clean_r2 = issue_clean_report(db, "night", ["A", "B"], "R2")
            assert [piece["piece_id"] for piece in clean_r2["included"]] == ["w"]
            assert [(piece["piece_id"], piece["matched_training_ids"])
                    for piece in clean_r2["excluded"]] == [("z", ["A"]), ("y", ["B"])]
            assert clean_r2["mean_difference"] == Fraction(-1, 2)
            # Missing attribution stays pending with no report or receipt.
            pending = issue_clean_report(db, "night", ["A", "B"], "Rwait")
            assert pending == {"status": "pending"}
            # Every piece matched: the report is still signed with a null mean.
            clean_all = issue_clean_report(db, "night", ["A", "B"], "Rall")
            assert clean_all["included"] == [] and clean_all["mean_difference"] is None
            assert {piece["piece_id"]: piece["matched_training_ids"]
                    for piece in clean_all["excluded"]} == {
                "z": ["A"], "y": ["A", "B"], "w": ["A", "B"]}
        with open_ledger(path) as db:
            initialize(db)
            # Reopen: stored values are re-issued by id, later attributions do not alter them.
            reopened_r1 = read_clean_report(db, clean_r1["report_id"])
            assert reopened_r1 == clean_r1
            assert reopened_r1["mean_difference"] == Fraction(-1, 6)
            assert read_clean_report(db, clean_r2["report_id"])["mean_difference"] == Fraction(-1, 2)
            assert json.loads(export_clean_report(db, clean_all["report_id"]))["mean_difference"] is None
            assert read_report(db, report.report_id) == report

    print(exported)
    _print_clean("R1 归档前签存", clean_r1)
    _print_clean("R2 归档后换版", clean_r2)
    print(f"Rwait 待证: {pending}")
    _print_clean("Rall 全排除", clean_all)
    print(f"重开领取 R1 存值: mean_difference={reopened_r1['mean_difference']} "
          f"receipt={reopened_r1['receipt_id']}")
    print("POINTWISE_SCENARIO " + json.dumps({
        "case_id": "leakage",
        "training_scans": {"A": ["s1", "s2"], "B": ["s3"]},
        "r1_mean": "-1/6",
        "r2_included": ["w"],
        "r2_excluded": {"z": ["A"], "y": ["B"]},
        "r2_mean": "-1/2",
        "rwait": pending,
        "rall_mean": None,
        "reopen_r1_mean": str(reopened_r1["mean_difference"]),
        "code_paths": [
            "training/lineage.py", "training/receipts.py", "ratings/clean.py",
            "ratings/clean_ledger.py", "retention/sweep.py",
        ],
        "oracle": "Transitive patch lineage to original scans, seam matching under named "
                  "attributions, exact Fraction Brier means over included roster pieces.",
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
