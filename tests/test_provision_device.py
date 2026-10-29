"""Local synthetic databases/tokens only; no deployment or pairing."""
import hashlib
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from bridge.core import Denied, Store
from bridge import provision_device

TOKEN = 'synthetic-test-only-' + 'A' * 32
OTHER = 'synthetic-test-only-' + 'B' * 32


class ProvisionDevice(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'devices.sqlite'

    def rows(self):
        store = Store(self.path)
        try:
            return [tuple(r) for r in store.db.execute('SELECT id,digest,revoked FROM devices ORDER BY id')]
        finally:
            store.close()

    def test_idempotent_hashed_and_authenticatable_boundaries(self):
        for size in (40, 256):
            token = ('!~Az09_' * 37)[:size]
            device = 'test_' + str(size)
            provision_device.provision(self.path, device, token)
            before = self.rows()
            with patch.object(provision_device.hmac, 'compare_digest', wraps=provision_device.hmac.compare_digest) as compare:
                provision_device.provision(self.path, device, token)
                compare.assert_called_once_with(next(r[1] for r in before if r[0] == device),
                                                hashlib.sha256(token.encode()).hexdigest())
            self.assertEqual(self.rows(), before)
            store = Store(self.path)
            try:
                self.assertEqual(store.authenticate(token), device)
            finally:
                store.close()
            self.assertIn((device, hashlib.sha256(token.encode()).hexdigest(), 0), before)
            self.assertNotIn(token, repr(before))

    def test_mismatch_revocation_and_duplicate_key_preserve_rows(self):
        provision_device.provision(self.path, 'device', TOKEN)
        before = self.rows()
        for device, token in [('device', OTHER), ('different', TOKEN)]:
            with self.subTest(device=device), self.assertRaises(ValueError):
                provision_device.provision(self.path, device, token)
            self.assertEqual(self.rows(), before)
        store = Store(self.path)
        store.revoke('device')
        store.close()
        before = self.rows()
        with self.assertRaisesRegex(ValueError, 'revoked'):
            provision_device.provision(self.path, 'device', TOKEN)
        self.assertEqual(self.rows(), before)

    def test_invalid_inputs_fail_before_opening_db(self):
        tokens = ['', 'a' * 39, 'a' * 257, TOKEN + ' ', TOKEN + '\n',
                  TOKEN + '\t', TOKEN + '\x00', TOKEN + '\x7f', TOKEN + 'é', None]
        for token in tokens:
            with self.subTest(token_type=type(token).__name__), self.assertRaises(ValueError):
                provision_device.provision(self.path, 'device', token)
            self.assertFalse(self.path.exists())
        with self.assertRaises(Denied):
            provision_device.provision(self.path, '../invalid', TOKEN)
        self.assertFalse(self.path.exists())

    def test_two_writers_same_key_or_conflict(self):
        # Both connections open before either starts the provisioning transaction.
        for second in (TOKEN, OTHER):
            with self.subTest(same=second == TOKEN), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'race.sqlite'
                Store(path).close()
                barrier = threading.Barrier(2)
                def opened(path):
                    store = Store(path)
                    barrier.wait(timeout=5)
                    return store
                def attempt(token):
                    try:
                        provision_device.provision(path, 'device', token)
                        return True
                    except ValueError:
                        return False
                with patch.object(provision_device, 'Store', side_effect=opened), ThreadPoolExecutor(2) as pool:
                    futures = [pool.submit(attempt, token) for token in (TOKEN, second)]
                    results = [f.result(timeout=15) for f in futures]
                self.assertEqual(sum(results), 2 if second == TOKEN else 1)
                store = Store(path)
                try:
                    rows = list(store.db.execute('SELECT digest,revoked FROM devices'))
                    self.assertEqual(len(rows), 1)
                    self.assertEqual(rows[0]['revoked'], 0)
                    self.assertIn(rows[0]['digest'], [hashlib.sha256(t.encode()).hexdigest() for t in (TOKEN, second)])
                finally:
                    store.close()
