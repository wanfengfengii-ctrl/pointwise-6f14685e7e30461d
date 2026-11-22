from fractions import Fraction
import json
import sqlite3

from quality.batches import read_frozen_batch
from quality.freeze import freeze_test
from ratings.export import export_report
from ratings.issue import issue_report
from ratings.read import read_report
from tests.support import LedgerCase
from weldbook import open_ledger


class RatingTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.register_evaluation()

    def test_exact_paired_mean(self):
        batch = self.freeze_example()
        self.assertEqual(read_frozen_batch(self.db, 'night'), batch)
        report = issue_report(self.db, 'night')
        self.assertEqual(report.training_ids, ('A', 'B'))
        self.assertEqual(report.batch_id, 'night')
        self.assertEqual([(score.row.piece_id, score.row.scan_id, score.row.actual) for score in report.scores],
                         [('t9', 'z', 0), ('t2', 'w', 1)])
        self.assertEqual([(s.first_error, s.second_error, s.difference) for s in report.scores], [
            (Fraction(1, 9), Fraction(1, 4), Fraction(-5, 36)),
            (Fraction(1, 9), Fraction(9, 16), Fraction(-65, 144)),
        ])
        self.assertEqual(report.mean_difference, Fraction(-85, 288))
        self.assertEqual(read_report(self.db, report.report_id), report)

    def test_permuted_predictions(self):
        batch = self.freeze_example(second=self.second[::-1])
        self.assertEqual([row.piece_id for row in batch.rows], ['t9', 't2'])
        self.assertEqual([row.second for row in batch.rows], [Fraction(1, 2), Fraction(1, 4)])
        self.freeze_example('regular')
        permuted = issue_report(self.db, 'night')
        regular = issue_report(self.db, 'regular')
        self.assertEqual(permuted.scores, regular.scores)
        self.assertEqual(permuted.mean_difference, Fraction(-85, 288))

    def test_empty_roster(self):
        batch = freeze_test(self.db, 'empty', ('A', 'B'), [], [], [('A', []), ('B', [])])
        self.assertEqual(batch.rows, ())
        report = issue_report(self.db, 'empty')
        self.assertEqual(report.scores, ())
        self.assertIsNone(report.mean_difference)
        self.assertEqual(read_report(self.db, report.report_id), report)
        decoded = json.loads(export_report(self.db, report.report_id))
        self.assertIsNone(decoded['mean_difference'])
        self.assertEqual(decoded['rows'], [])

    def test_bad_probability(self):
        for value in ((4, 3), (1, 0), (0, -1), (True, 2), -1, 0.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.freeze_example(first=[('t9', value), self.first[1]])
                with self.assertRaises(KeyError):
                    read_frozen_batch(self.db, 'night')
        for table in ('frozen_batches', 'frozen_rows', 'label_records', 'prediction_groups', 'prediction_records'):
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)

    def test_missing_label(self):
        with self.assertRaisesRegex(ValueError, 't9'):
            self.freeze_example(labels=[('t2', 1)])
        with self.assertRaises(KeyError):
            read_frozen_batch(self.db, 'night')
        with self.assertRaises(KeyError):
            issue_report(self.db, 'night')

    def test_complete_retry(self):
        with self.assertRaises(ValueError):
            self.freeze_example(labels=[('t2', 1)])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM label_records').fetchone()[0], 0)
        batch = self.freeze_example(labels=self.labels[::-1])
        self.assertEqual([(row.piece_id, row.actual) for row in batch.rows], [('t9', 0), ('t2', 1)])
        self.assertEqual(issue_report(self.db, 'night').mean_difference, Fraction(-85, 288))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM frozen_batches').fetchone()[0], 1)

    def test_mismatched_training_and_unknown_scan(self):
        with self.assertRaises(ValueError):
            freeze_test(self.db, 'night', ('A', 'B'), self.roster, self.labels,
                        [('B', self.first), ('A', self.second)])
        self.roster[1] = ('t2', 'missing-scan')
        with self.assertRaisesRegex(KeyError, 'missing-scan'):
            self.freeze_example()
        with self.assertRaises(KeyError):
            read_frozen_batch(self.db, 'night')

    def test_bad_roster_and_incomplete_prediction(self):
        with self.assertRaises(ValueError):
            self.freeze_example(second=self.second[:1])
        with self.assertRaises(ValueError):
            self.freeze_example(labels=[('t9', False), ('t2', 1)])
        self.roster[1] = ('t9', 'w')
        with self.assertRaises(ValueError):
            self.freeze_example()
        with self.assertRaises(KeyError):
            read_frozen_batch(self.db, 'night')

    def test_issue_commit_failure(self):
        self.freeze_example()
        self.db.execute('''
            CREATE TEMP TRIGGER fail_receipt BEFORE INSERT ON issue_receipts
            BEGIN
                SELECT CASE WHEN
                    (SELECT COUNT(*) FROM signed_reports WHERE report_id = NEW.report_id) <> 1
                    OR (SELECT COUNT(*) FROM report_rows WHERE report_id = NEW.report_id) <> 2
                THEN RAISE(ABORT, 'fixture did not reach the report boundary') END;
                SELECT RAISE(ABORT, 'receipt write rejected');
            END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'receipt write rejected'):
            issue_report(self.db, 'night')
        with open_ledger(self.path) as reader:
            for table in ('signed_reports', 'report_rows', 'issue_receipts'):
                self.assertEqual(reader.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
            with self.assertRaises(KeyError):
                read_report(reader, 1)
        self.db.execute('DROP TRIGGER fail_receipt')
        report = issue_report(self.db, 'night')
        with open_ledger(self.path) as reader:
            self.assertEqual(read_report(reader, report.report_id), report)
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM signed_reports').fetchone()[0], 1)
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM report_rows').fetchone()[0], 2)
            self.assertEqual(reader.execute('SELECT COUNT(*) FROM issue_receipts').fetchone()[0], 1)
        self.assertEqual(report.receipt.report_id, report.report_id)
        self.assertEqual(report.mean_difference, Fraction(-85, 288))

    def test_unknown_batch(self):
        with self.assertRaises(KeyError):
            issue_report(self.db, 'missing-batch')
        with self.assertRaises(ValueError):
            issue_report(self.db, '')
        for table in ('signed_reports', 'report_rows', 'issue_receipts'):
            self.assertEqual(self.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0], 0)
