"""Local idempotent provisioning; never rotates keys or clears revocation.

Run with python -m bridge.provision_device --db PATH --device ID --token-file PATH.
Token file must contain exactly 40-256 printable ASCII bytes, without whitespace
(including a trailing newline). No token is accepted on the command line.
"""
import argparse
import hashlib
import hmac
import sqlite3
from pathlib import Path

from .core import Store, ident


def provision(path, device, token):
    ident(device)
    if (not isinstance(token, str) or not 40 <= len(token) <= 256
            or any(not 33 <= ord(c) <= 126 for c in token)):
        raise ValueError('Device token must be 40-256 printable ASCII characters without whitespace')
    digest = hashlib.sha256(token.encode('ascii')).hexdigest()
    store = Store(path)
    try:
        # Serialize check + insert with other writers, including revocation.
        store.db.execute('BEGIN IMMEDIATE')
        try:
            row = store.db.execute('SELECT digest,revoked FROM devices WHERE id=?', (device,)).fetchone()
            if row:
                if row['revoked'] or not hmac.compare_digest(row['digest'], digest):
                    raise ValueError('Existing device token differs or is revoked; refusing implicit rotation')
            else:
                try:
                    store.provision(device, token)
                except sqlite3.IntegrityError:
                    raise ValueError('Device token already assigned; refusing implicit reassignment') from None
            store.db.execute('COMMIT')
        except BaseException:
            store.db.execute('ROLLBACK')
            raise
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--device', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    args = parser.parse_args()
    try:
        # Bound reads; do not trim or normalize an invalid file into a valid key.
        with args.token_file.open('rb') as source:
            token = source.read(257).decode('ascii')
        provision(args.db, args.device, token)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, 'Device provisioning failed; token not printed.\n')
    print('Device API key provisioned/verified; token not printed.')


if __name__ == '__main__':
    main()
