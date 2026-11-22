from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from quality.freeze import freeze_test
from scans.register import register_scan
from scans.seams import register_seam
from training.finish import finish_training
from training.parents import ParentRef
from training.patches import revise_patch
from weldbook import initialize, open_ledger


class LedgerCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='weldbook-test-'))
        self.path = Path(directory) / 'ledger.sqlite3'
        self.db = self.enterContext(open_ledger(self.path))
        initialize(self.db)

    def register_materials(self):
        register_seam(self.db, 'W1', 'first bench')
        register_seam(self.db, 'W2', 'second bench')
        self.s1 = register_scan(self.db, 'W1', 's1', 'capture-1', b'raw-1', 10)
        self.s2 = register_scan(self.db, 'W1', 's2', 'capture-2', b'raw-2', 10)
        self.p1 = revise_patch(self.db, 'P', 'p1', [ParentRef('scan', 's1')], b'patch-1', 10)
        self.q1 = revise_patch(self.db, 'Q', 'q1', [ParentRef('scan', 's2')], b'patch-q', 30)

    def register_evaluation(self):
        self.register_materials()
        self.z = register_scan(self.db, 'W2', 'z', 'capture-z', b'test-z', 10)
        self.w = register_scan(self.db, 'W2', 'w', 'capture-w', b'test-w', 10)
        finish_training(self.db, 'A', ['p1'])
        finish_training(self.db, 'B', ['q1'])
        self.roster = [('t9', 'z'), ('t2', 'w')]
        self.labels = [('t9', 0), ('t2', 1)]
        self.first = [('t9', (1, 3)), ('t2', (2, 3))]
        self.second = [('t9', (1, 2)), ('t2', (1, 4))]

    def freeze_example(self, batch_id='night', *, labels=None, first=None, second=None):
        return freeze_test(
            self.db, batch_id, ('A', 'B'), self.roster, self.labels if labels is None else labels,
            [('A', self.first if first is None else first), ('B', self.second if second is None else second)],
        )
