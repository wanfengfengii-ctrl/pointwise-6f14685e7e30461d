from fractions import Fraction
import json
from pathlib import Path
import sqlite3

from leakage_shift import publish_review_revisions, retire_shift, seed_shift
from quality.freeze import freeze_test
from ratings.clean import (
    export_clean_report,
    issue_clean_report,
    read_clean_report,
)
from ratings.issue import issue_report
from ratings.read import read_report
from retention.holds import HoldTarget
from retention.sweep import sweep_due
from scans.attribution import publish_attribution
from scans.register import register_scan
from tempfile import TemporaryDirectory
from tests.support import LedgerCase
from training.finish import finish_training
from training.parents import ParentRef
from training.patches import revise_patch
from training.receipts import read_training_scans
from training.work_orders import checkout_training_materials
from weldbook import initialize, open_ledger


class LeakageScenarioCase(LedgerCase):
    def setUp(self):
        super().setUp()
        self.batch = seed_shift(self.db)

    def _review(self):
        retire_shift(self.db)
        publish_review_revisions(self.db)

    def test_training_scans_follow_actual_consumed_lineage(self):
        self.assertEqual(read_training_scans(self.db, 'A'), ('s1', 's2'))
        self.assertEqual(read_training_scans(self.db, 'B'), ('s3',))

    def test_training_scans_survive_indirect_parent_retirement(self):
        self._review()
        self.assertEqual(read_training_scans(self.db, 'A'), ('s1', 's2'))
        self.assertEqual(read_training_scans(self.db, 'B'), ('s3',))

    def test_r1_keeps_full_roster(self):
        report = issue_clean_report(self.db, 'night', ['A', 'B'], 'R1')
        self.assertEqual(report['status'], 'signed')
        self.assertIsInstance(report['report_id'], int)
        self.assertTrue(report['report_id'] > 0)
        self.assertEqual(report['receipt_id'], f"clean-{report['report_id']}")
        self.assertEqual(report['batch_id'], 'night')
        self.assertEqual(report['training_ids'], ['A', 'B'])
        self.assertEqual(report['attribution_id'], 'R1')
        self.assertEqual(report['training_scans'], [['s1', 's2'], ['s3']])
        self.assertEqual([piece['piece_id'] for piece in report['included']], ['z', 'y', 'w'])
        self.assertEqual(report['excluded'], [])
        self.assertEqual(report['mean_difference'], Fraction(-1, 6))
        self.assertEqual(read_clean_report(self.db, report['report_id']), report)

    def test_r2_excludes_matching_seams_after_attribution_change(self):
        self._review()
        report = issue_clean_report(self.db, 'night', ['A', 'B'], 'R2')
        self.assertEqual([piece['piece_id'] for piece in report['included']], ['w'])
        self.assertEqual(
            [(piece['piece_id'], piece['scan_id'], piece['seam_id'], piece['matched_training_ids'])
             for piece in report['excluded']],
            [('z', 'z', 'W2', ['A']), ('y', 'y', 'W3', ['B'])],
        )
        self.assertEqual(report['mean_difference'], Fraction(-1, 2))
        self.assertEqual(read_clean_report(self.db, report['report_id']), report)

    def test_rwait_is_pending_without_receipt(self):
        self._review()
        before = self.db.execute('SELECT COUNT(*) FROM clean_reports').fetchone()[0]
        self.assertEqual(issue_clean_report(self.db, 'night', ['A', 'B'], 'Rwait'), {'status': 'pending'})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM clean_reports').fetchone()[0], before)

    def test_rall_excludes_everything_with_null_mean(self):
        self._review()
        report = issue_clean_report(self.db, 'night', ['A', 'B'], 'Rall')
        self.assertEqual(report['included'], [])
        self.assertIsNone(report['mean_difference'])
        self.assertEqual(
            {piece['piece_id']: piece['matched_training_ids'] for piece in report['excluded']},
            {'z': ['A'], 'y': ['A', 'B'], 'w': ['A', 'B']},
        )
        body = json.loads(export_clean_report(self.db, report['report_id']))
        self.assertIsNone(body['mean_difference'])
        self.assertEqual(body['status'], 'signed')

    def test_signed_values_survive_reopen_and_new_attributions(self):
        r1 = issue_clean_report(self.db, 'night', ['A', 'B'], 'R1')
        v1 = issue_report(self.db, 'night')
        with open_ledger(self.path) as db:
            initialize(db)
            retire_shift(db)
            publish_review_revisions(db)
            self.assertEqual(read_clean_report(db, r1['report_id']), r1)
            self.assertEqual(read_report(db, v1.report_id), v1)
            r2 = issue_clean_report(db, 'night', ['A', 'B'], 'R2')
            self.assertEqual(r2['mean_difference'], Fraction(-1, 2))
            self.assertEqual(read_clean_report(db, r1['report_id'])['mean_difference'], Fraction(-1, 6))

    def test_export_uses_decimal_strings_and_roster_order(self):
        self._review()
        report = issue_clean_report(self.db, 'night', ['A', 'B'], 'R2')
        body = json.loads(export_clean_report(self.db, report['report_id']))
        self.assertEqual(body['mean_difference'], {'numerator': '-1', 'denominator': '2'})
        self.assertEqual([piece['piece_id'] for piece in body['included']], ['w'])
        self.assertEqual([piece['piece_id'] for piece in body['excluded']], ['z', 'y'])
        self.assertEqual(body['training_ids'], ['A', 'B'])
        self.assertEqual(body['training_scans'], [['s1', 's2'], ['s3']])
        self.assertEqual(body['attribution_id'], 'R2')

    def test_pending_when_training_lineage_incomplete(self):
        self._review()
        self.db.execute('DELETE FROM revision_parent_evidence WHERE revision_id = ?', ('m1',))
        self.db.execute('DELETE FROM patch_parents WHERE revision_id = ?', ('m1',))
        self.assertIsNone(read_training_scans(self.db, 'A'))
        self.assertEqual(issue_clean_report(self.db, 'night', ['A', 'B'], 'R2'), {'status': 'pending'})

    def test_commit_failure_leaves_no_report_and_retries(self):
        self.db.execute('''
            CREATE TEMP TRIGGER fail_clean_receipt BEFORE INSERT ON clean_report_receipts
            BEGIN
                SELECT CASE WHEN
                    (SELECT COUNT(*) FROM clean_reports) <> 1
                    OR (SELECT COUNT(*) FROM clean_report_pieces) <> 3
                THEN RAISE(ABORT, 'fixture did not reach the report boundary') END;
                SELECT RAISE(ABORT, 'clean receipt write rejected');
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'clean receipt write rejected'):
            issue_clean_report(self.db, 'night', ['A', 'B'], 'R1')
        for table in ('clean_reports', 'clean_report_pieces', 'clean_report_matches',
                      'clean_report_scans', 'clean_report_receipts'):
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
        self.db.execute('DROP TRIGGER fail_clean_receipt')
        report = issue_clean_report(self.db, 'night', ['A', 'B'], 'R1')
        self.assertEqual(report['mean_difference'], Fraction(-1, 6))
        self.assertEqual(read_clean_report(self.db, report['report_id']), report)

    def test_invalid_and_mismatched_arguments(self):
        with self.assertRaises(ValueError):
            issue_clean_report(self.db, 'night', ['B', 'A'], 'R1')
        with self.assertRaises(ValueError):
            issue_clean_report(self.db, 'night', ['A', 'A'], 'R1')
        with self.assertRaises(ValueError):
            issue_clean_report(self.db, 'night', ['A'], 'R1')
        with self.assertRaises(ValueError):
            issue_clean_report(self.db, 'night', 'A', 'R1')
        with self.assertRaises(ValueError):
            issue_clean_report(self.db, '', ['A', 'B'], 'R1')
        with self.assertRaises(ValueError):
            issue_clean_report(self.db, 'night', ['A', 'B'], ' R1')
        with self.assertRaises(KeyError):
            issue_clean_report(self.db, 'missing-batch', ['A', 'B'], 'R1')
        with self.assertRaises(KeyError):
            issue_clean_report(self.db, 'night', ['A', 'B'], 'missing-revision')
        with self.assertRaises(KeyError):
            read_clean_report(self.db, 99)
        with self.assertRaises(ValueError):
            read_clean_report(self.db, 0)
        with self.assertRaises(KeyError):
            read_training_scans(self.db, 'missing-training')
        with self.assertRaises(ValueError):
            read_training_scans(self.db, '  ')


class LineageEvidenceTests(LedgerCase):
    def test_legacy_ledger_complete_production_lineage(self):
        legacy = Path(__file__).resolve().parent.parent / 'samples' / 'early-shift.sql'
        self.db.executescript(legacy.read_text(encoding='utf-8'))
        self.assertEqual(read_training_scans(self.db, 'early-run'), ('early-scan',))

    def test_legacy_ledger_lost_parents_stays_pending(self):
        legacy = Path(__file__).resolve().parent.parent / 'samples' / 'early-shift.sql'
        self.db.executescript(legacy.read_text(encoding='utf-8'))
        self.db.execute('DELETE FROM patch_parents WHERE revision_id = ?', ('early-r1',))
        self.assertIsNone(read_training_scans(self.db, 'early-run'))

    def test_multi_level_multi_parent_dedup_and_rescan(self):
        self.register_materials()
        register_scan(self.db, 'W1', 's1b', 'capture-1b', b'raw-1b', 30)
        revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's1'), ParentRef('scan', 's1b')], b'p2', 30)
        revise_patch(
            self.db, 'M', 'm1',
            [ParentRef('patch', 'p1'), ParentRef('patch', 'p2'), ParentRef('scan', 's1')],
            b'mix', 30,
        )
        finish_training(self.db, 'A', ['m1'])
        self.assertEqual(read_training_scans(self.db, 'A'), ('s1', 's1b'))
        sweep_due(self.db, 10)
        revise_patch(self.db, 'M', 'm2', [ParentRef('scan', 's2')], b'mix2', 40)
        sweep_due(self.db, 30)
        self.assertEqual(read_training_scans(self.db, 'A'), ('s1', 's1b'))

    def test_checked_out_but_unconsumed_material_is_excluded(self):
        self.register_materials()
        checkout_training_materials(
            self.db, 'A',
            [HoldTarget('patch', 'p1'), HoldTarget('definition', 'p1'), HoldTarget('patch', 'q1')],
        )
        finish_training(self.db, 'A', ['p1'])
        self.assertEqual(read_training_scans(self.db, 'A'), ('s1',))


class CleanReportOrderTests(LedgerCase):
    def test_roster_order_and_shared_scan_pieces_listed_separately(self):
        self.register_evaluation()
        publish_attribution(self.db, 'R', {'s1': 'W1', 's2': 'W1', 'z': 'W2', 'w': 'W2'})
        freeze_test(
            self.db, 'dup', ('A', 'B'), [('k1', 'z'), ('k2', 'z'), ('k3', 'w')],
            [('k1', 0), ('k2', 1), ('k3', 0)],
            [('A', [('k1', 0), ('k2', (1, 2)), ('k3', (1, 4))]),
             ('B', [('k1', 0), ('k2', (1, 2)), ('k3', (3, 4))])],
        )
        report = issue_clean_report(self.db, 'dup', ['A', 'B'], 'R')
        self.assertEqual([piece['piece_id'] for piece in report['included']], ['k1', 'k2', 'k3'])
        self.assertEqual(report['excluded'], [])
        publish_attribution(self.db, 'R2', {'s1': 'W1', 's2': 'W1', 'z': 'W1', 'w': 'W2'})
        report2 = issue_clean_report(self.db, 'dup', ['A', 'B'], 'R2')
        self.assertEqual([piece['piece_id'] for piece in report2['included']], ['k3'])
        self.assertEqual(
            [(piece['piece_id'], piece['matched_training_ids']) for piece in report2['excluded']],
            [('k1', ['A', 'B']), ('k2', ['A', 'B'])],
        )
        only = (Fraction(1, 4) ** 2) - (Fraction(3, 4) ** 2)
        self.assertEqual(report2['mean_difference'], only)
