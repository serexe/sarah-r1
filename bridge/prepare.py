"""Local provisioning only. Does not connect to providers or devices."""
import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit
from .core import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--device', default='example-device')
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('', '/'):
        parser.error('origin must be an HTTPS origin without credentials, path, query or fragment')
    os.umask(0o077)
    args.state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.state.is_symlink() or args.state.stat().st_mode & 0o077:
        parser.error('state directory must be private and not a symlink')
    settings = args.state / 'native-settings.json'
    if settings.exists() or (args.state/'state.db').exists():
        parser.error('existing provisioning retained; refusing overwrite')
    token = secrets.token_urlsafe(48)
    store = Store(args.state/'state.db')
    try:
        store.provision(args.device, token)
    finally:
        store.close()
    with settings.open('x', encoding='utf-8') as output:
        json.dump(dict(base=args.origin.rstrip('/'), token=token, conversation='', turn='', request='', transcript=''), output)
    print('Prepared private state.db and native-settings.json; token not printed.')


if __name__ == '__main__':
    main()
