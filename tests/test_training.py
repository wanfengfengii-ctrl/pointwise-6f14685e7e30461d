from retention.holds import HoldTarget, active_holders
from retention.payloads import PayloadRef, read_payload
from retention.sweep import sweep_due
from scans.attribution import publish_attribution, read_scan_attribution
from scans.read import read_scan
from scans.register import intake_unassigned_scan, register_scan
from tests.support import LedgerCase
from training.finish import finish_training
from training.parents import ParentRef, read_parent_refs
from training.patches import read_patch_revision, revise_patch
from training.receipts import read_training_receipt
from training.work_orders import checkout_training_materials, read_work_order
from weldbook import open_ledger


class TrainingTests(LedgerCase):
    def setUp(self):
        super().setUp()
        self.register_materials()

    def test_finish_pins_used_revision(self):
        receipt = finish_training(self.db, 'A', ['p1'])
        p2 = revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's2')], b'new', 30)
        self.assertEqual(receipt.revision_ids, ('p1',))
        self.assertEqual(read_training_receipt(self.db, 'A'), receipt)
        self.assertTrue(read_patch_revision(self.db, 'p1').superseded)
        self.assertEqual(read_patch_revision(self.db, 'p1').parents, (ParentRef('scan', 's1'),))
        self.assertEqual(p2.parents, (ParentRef('scan', 's2'),))

    def test_actual_subset(self):
        held = HoldTarget('patch', 'p1'), HoldTarget('patch', 'q1')
        checkout_training_materials(self.db, 'A', held)
        receipt = finish_training(self.db, 'A', ['p1'])
        revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's2')], b'new', 30)
        self.assertEqual(read_training_receipt(self.db, 'A').revision_ids, ('p1',))
        self.assertEqual(read_training_receipt(self.db, 'A'), receipt)
        self.assertEqual(read_parent_refs(self.db, 'p1'), (ParentRef('scan', 's1'),))
        order = read_work_order(self.db, 'A')
        self.assertEqual(order.targets, held)
        self.assertTrue(order.closed)
        self.assertEqual([active_holders(self.db, target) for target in held], [(), ()])

    def test_unavailable_input(self):
        target = HoldTarget('definition', 'p1')
        checkout_training_materials(self.db, 'A', [target])
        sweep_due(self.db, 10)
        self.assertEqual(read_patch_revision(self.db, 'p1').revision_id, 'p1')
        with self.assertRaises(ValueError):
            finish_training(self.db, 'A', ['p1'])
        with self.assertRaises(KeyError):
            read_training_receipt(self.db, 'A')
        self.assertFalse(read_work_order(self.db, 'A').closed)
        self.assertEqual(active_holders(self.db, target), ('A',))
        with self.assertRaises(KeyError):
            finish_training(self.db, 'B', ['unknown-revision'])

    def test_missing_parent(self):
        with self.assertRaisesRegex(KeyError, 'unknown-scan'):
            revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 'unknown-scan')], b'bad', 30)
        with self.assertRaises(KeyError):
            read_patch_revision(self.db, 'p2')
        with self.assertRaises(KeyError):
            read_payload(self.db, PayloadRef('patch', 'p2'))
        self.assertFalse(read_patch_revision(self.db, 'p1').superseded)
        p2 = revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's1')], b'good', 30)
        self.assertEqual(read_payload(self.db, p2.payload), b'good')

    def test_second_parent_missing(self):
        first = ParentRef('patch', 'p1')
        with self.assertRaisesRegex(KeyError, 'missing-patch'):
            revise_patch(self.db, 'Mix', 'm1', [first, ParentRef('patch', 'missing-patch')], b'bad', 30)
        with self.assertRaises(KeyError):
            read_patch_revision(self.db, 'm1')
        with self.assertRaises(KeyError):
            read_payload(self.db, PayloadRef('patch', 'm1'))
        expected = (first, ParentRef('patch', 'q1'))
        revise_patch(self.db, 'Mix', 'm1', expected, b'good', 30)
        self.assertEqual(read_parent_refs(self.db, 'm1'), expected)
        self.assertEqual(read_payload(self.db, PayloadRef('patch', 'm1')), b'good')
        self.assertEqual(finish_training(self.db, 'Mix-A', ['m1']).revision_ids, ('m1',))

    def test_rescan_identity(self):
        for revision_id, scan_id, capture, pixels in (
            ('p1', 's1', 'capture-1', b'raw-1'), ('q1', 's2', 'capture-2', b'raw-2'),
        ):
            with self.subTest(revision=revision_id):
                (parent,) = read_parent_refs(self.db, revision_id)
                self.assertEqual(parent, ParentRef('scan', scan_id))
                scan = read_scan(self.db, parent.key)
                self.assertEqual((scan.capture_sheet, scan.initial_seam), (capture, 'W1'))
                self.assertEqual(read_payload(self.db, scan.payload), pixels)
        self.assertNotEqual(self.s1.payload, self.s2.payload)

    def test_named_attribution(self):
        publish_attribution(self.db, 'R1', [('s1', 'W1'), ('s2', 'W1')])
        with self.assertRaises(KeyError):
            publish_attribution(self.db, 'R2', [('s1', 'W2'), ('s2', 'unknown-weld')])
        with self.assertRaises(KeyError):
            read_scan_attribution(self.db, 'R2', 's1')
        publish_attribution(self.db, 'R2', [('s1', 'W2')])
        with open_ledger(self.path) as db:
            self.assertEqual(read_scan_attribution(db, 'R1', 's1'), 'W1')
            self.assertEqual(read_scan_attribution(db, 'R2', 's1'), 'W2')
            self.assertIsNone(read_scan_attribution(db, 'R2', 's2'))
            self.assertEqual(read_scan(db, 's1').initial_seam, 'W1')
        with self.assertRaises(ValueError):
            publish_attribution(self.db, 'R2', [('s1', 'W1')])

    def test_unassigned_scan(self):
        scan = intake_unassigned_scan(self.db, 'u1', 'capture-pending', b'pending', 12)
        self.assertIsNone(scan.initial_seam)
        publish_attribution(self.db, 'R', {'s1': 'W1'})
        self.assertIsNone(read_scan_attribution(self.db, 'R', 'u1'))
        with self.assertRaises(KeyError):
            read_scan_attribution(self.db, 'R', 'unknown-scan')
        with self.assertRaises(ValueError):
            intake_unassigned_scan(self.db, 's1', 'different', b'bad', 12)
        with self.assertRaises(KeyError):
            register_scan(self.db, 'unknown-weld', 'new', 'capture-new', b'new', 12)
        with self.assertRaises(ValueError):
            register_scan(self.db, 'W1', 'new', 'capture-new', b'', 12)
        with self.assertRaises(KeyError):
            read_scan(self.db, 'new')
        self.assertEqual(read_scan(self.db, 's1'), self.s1)
        self.assertEqual(read_payload(self.db, scan.payload), b'pending')

    def test_direct_checkout_and_ancestor_definition_have_independent_lifetimes(self):
        parent = ParentRef('patch', 'p1')
        leaf = revise_patch(self.db, 'Mix', 'm1', [parent, ParentRef('scan', 's2')], b'mix', 30)
        checkout_training_materials(self.db, 'A', [HoldTarget('patch', 'm1'), HoldTarget('definition', 'm1')])
        revise_patch(self.db, 'P', 'p2', [ParentRef('scan', 's2')], b'new', 30)
        retired = sweep_due(self.db, 10)
        self.assertIn(HoldTarget('definition', 'p1'), {receipt.target for receipt in retired.retired})
        with self.assertRaises(ValueError):
            read_parent_refs(self.db, 'p1')
        self.assertEqual(read_patch_revision(self.db, 'm1').parents, leaf.parents)
        self.assertEqual(finish_training(self.db, 'A', ['m1']).revision_ids, ('m1',))
