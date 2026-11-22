from fractions import Fraction
import json
from pathlib import Path
import sqlite3

from ratings.export import export_report
from ratings.issue import issue_report
from ratings.read import read_report
from retention.holds import HoldTarget
from retention.payloads import read_payload, read_payload_status
from retention.retire import read_retirement_receipt
from retention.sweep import sweep_due
from scans.attribution import publish_attribution, read_scan_attribution
from scans.read import read_scan
from tests.support import LedgerCase
from training.finish import finish_training
from training.parents import ParentRef
from training.patches import read_patch_revision, revise_patch
from training.receipts import read_training_receipt
from training.work_orders import checkout_training_materials
from weldbook import initialize, open_ledger


class RetentionTests(LedgerCase):
    def _signed_shift(self):
        self.register_evaluation()
        self.freeze_example(second=self.second[::-1])
        report = issue_report(self.db, 'night')
        revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's2')], b'new', 30)
        return report

    def test_report_survives_retirement(self):
        report = self._signed_shift()
        result = sweep_due(self.db, 10)
        retired = {receipt.target for receipt in result.retired}
        self.assertIn(HoldTarget('scan', 'z'), retired)
        self.assertIn(HoldTarget('patch', 'p1'), retired)
        self.assertIn(HoldTarget('definition', 'p1'), retired)
        with open_ledger(self.path) as db:
            self.assertEqual(read_scan(db, 'z').capture_sheet, 'capture-z')
            with self.assertRaises(ValueError):
                read_payload(db, self.z.payload)
            with self.assertRaises(ValueError):
                read_patch_revision(db, 'p1')
            self.assertEqual(read_training_receipt(db, 'A').revision_ids, ('p1',))
            restored = read_report(db, report.report_id)
            self.assertEqual(restored, report)
            self.assertEqual(restored.mean_difference, Fraction(-85, 288))
            self.assertEqual([score.row.piece_id for score in restored.scores], ['t9', 't2'])
            self.assertEqual(restored.training_ids, ('A', 'B'))
            self.assertEqual(sweep_due(db, 10).retired, ())

    def test_history_export(self):
        report = self._signed_shift()
        before = export_report(self.db, report.report_id)
        sweep_due(self.db, 10)
        with open_ledger(self.path) as db:
            self.assertEqual(export_report(db, report.report_id), before)
            self.assertEqual(read_report(db, report.report_id), report)
        payload = json.loads(before)
        self.assertEqual(payload['training_ids'], ['A', 'B'])
        self.assertEqual(payload['batch_id'], 'night')
        self.assertEqual([(r['position'], r['piece_id'], r['scan_id'], r['actual']) for r in payload['rows']],
                         [(0, 't9', 'z', 0), (1, 't2', 'w', 1)])
        self.assertEqual(payload['rows'][1]['probabilities'][1], {'numerator': '1', 'denominator': '4'})
        self.assertEqual(payload['rows'][1]['errors'][1], {'numerator': '9', 'denominator': '16'})
        self.assertEqual(payload['mean_difference'], {'numerator': '-85', 'denominator': '288'})
        self.assertEqual(payload['receipt']['receipt_id'], report.receipt.receipt_id)

    def test_init_replay(self):
        legacy = Path(__file__).resolve().parent.parent / 'samples' / 'early-shift.sql'
        self.db.executescript(legacy.read_text(encoding='utf-8'))
        report = self._signed_shift()
        publish_attribution(self.db, 'revised', [('early-scan', 'W2'), ('s1', 'W2')])
        sweep_due(self.db, 12)
        target = HoldTarget('scan', 'early-scan')
        expected = read_retirement_receipt(self.db, target)
        export = export_report(self.db, report.report_id)
        with open_ledger(self.path) as db:
            initialize(db)
            initialize(db)
            self.assertEqual(read_scan_attribution(db, 'early-register', 'early-scan'), 'early-weld')
            self.assertEqual(read_scan_attribution(db, 'revised', 'early-scan'), 'W2')
            self.assertEqual(read_scan_attribution(db, 'revised', 's1'), 'W2')
            self.assertEqual(read_training_receipt(db, 'early-run').revision_ids, ('early-r1',))
            self.assertEqual(read_report(db, report.report_id), report)
            self.assertEqual(export_report(db, report.report_id), export)
            self.assertEqual(read_retirement_receipt(db, target), expected)
            self.assertFalse(read_payload_status(db, read_scan(db, 'early-scan').payload).available)
            self.assertEqual(sweep_due(db, 12).retired, ())

    def test_active_training_protection(self):
        self.register_materials()
        targets = [HoldTarget('scan', 's1'), HoldTarget('patch', 'p1'), HoldTarget('definition', 'p1')]
        checkout_training_materials(self.db, 'A', targets)
        revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's2')], b'new', 30)
        result = sweep_due(self.db, 10)
        self.assertEqual({item.target: item.holders for item in result.protected}, {target: ('A',) for target in targets})
        self.assertEqual({receipt.target for receipt in result.retired}, {HoldTarget('scan', 's2')})
        self.assertEqual(read_payload(self.db, self.s1.payload), b'raw-1')
        self.assertEqual(read_payload(self.db, self.p1.payload), b'patch-1')
        self.assertEqual(read_patch_revision(self.db, 'p1').parents, (ParentRef('scan', 's1'),))
        with self.assertRaises(ValueError):
            read_payload(self.db, self.s2.payload)

    def test_shared_loan(self):
        self.register_materials()
        target = HoldTarget('patch', 'p1')
        checkout_training_materials(self.db, 'Q1', [target])
        checkout_training_materials(self.db, 'Q2', [target])
        first = sweep_due(self.db, 10)
        self.assertEqual([(item.target, item.holders) for item in first.protected], [(target, ('Q1', 'Q2'))])
        finish_training(self.db, 'Q1', ['p1'])
        second = sweep_due(self.db, 10)
        self.assertEqual([(item.target, item.holders) for item in second.protected], [(target, ('Q2',))])
        self.assertEqual(read_payload(self.db, self.p1.payload), b'patch-1')
        self.assertTrue(read_payload_status(self.db, self.q1.payload).available)
        self.assertFalse(read_payload_status(self.db, self.s2.payload).available)

    def test_release_same_cutoff(self):
        self.register_materials()
        target = HoldTarget('patch', 'p1')
        checkout_training_materials(self.db, 'Q1', [target])
        checkout_training_materials(self.db, 'Q2', [target])
        first = sweep_due(self.db, 10)
        earlier = {receipt.target for receipt in first.retired}
        finish_training(self.db, 'Q1', ['p1'])
        waiting = sweep_due(self.db, 10)
        self.assertEqual(waiting.retired, ())
        self.assertEqual(waiting.protected[0].holders, ('Q2',))
        finish_training(self.db, 'Q2', ['p1'])
        second = sweep_due(self.db, 10)
        self.assertEqual([receipt.target for receipt in second.retired], [target])
        self.assertNotIn(target, earlier)
        self.assertEqual(second.protected, ())
        with open_ledger(self.path) as db:
            self.assertEqual(read_retirement_receipt(db, target).cutoff, 10)
            self.assertEqual(sweep_due(db, 10).retired, ())
            self.assertEqual(sweep_due(db, 11).retired, ())
            count = db.execute('SELECT COUNT(*) FROM retirement_receipts').fetchone()[0]
            self.assertEqual(count, len(earlier) + 1)

    def test_cutoff_edges(self):
        self.register_materials()
        revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's2')], b'new', 30)
        for cutoff in (True, 10.0, '10', 2**63):
            with self.subTest(cutoff=cutoff), self.assertRaises(ValueError):
                sweep_due(self.db, cutoff)
        self.assertEqual(sweep_due(self.db, 9).retired, ())
        self.assertTrue(read_payload_status(self.db, self.s1.payload).available)
        at_expiry = sweep_due(self.db, 10)
        self.assertEqual({receipt.target for receipt in at_expiry.retired}, {
            HoldTarget('definition', 'p1'), HoldTarget('patch', 'p1'), HoldTarget('scan', 's1'), HoldTarget('scan', 's2'),
        })
        self.assertEqual(sweep_due(self.db, 30).protected, ())
        self.assertEqual(read_patch_revision(self.db, 'p2').revision_id, 'p2')
        self.assertFalse(read_payload_status(self.db, self.q1.payload).available)

    def test_sweep_write_failure_rolls_back_payload_and_definition(self):
        self.register_materials()
        revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's2')], b'new', 30)
        self.db.execute('''
            CREATE TEMP TRIGGER fail_retirement BEFORE INSERT ON retirement_receipts
            WHEN NEW.kind = 'scan'
            BEGIN
                SELECT RAISE(ABORT, 'retirement receipt rejected');
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'retirement receipt rejected'):
            sweep_due(self.db, 10)
        with open_ledger(self.path) as db:
            self.assertEqual(read_patch_revision(db, 'p1').parents, (ParentRef('scan', 's1'),))
            self.assertEqual(read_payload(db, self.p1.payload), b'patch-1')
            self.assertEqual(read_payload(db, self.s1.payload), b'raw-1')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM retirement_receipts').fetchone()[0], 0)
        self.db.execute('DROP TRIGGER fail_retirement')
        self.assertEqual(len(sweep_due(self.db, 10).retired), 4)
