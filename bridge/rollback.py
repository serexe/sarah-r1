"""Private immutable local rollback exports; never returned to model/device."""
import json
import os
import uuid
from pathlib import Path

DEFAULT_BACKUP = Path(__file__).resolve().parents[1]/'.state'/'rollback'

def save_export(directory, source, identity, content):
    directory=Path(directory)
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise RuntimeError('rollback_directory_not_private')
    path=directory/(source+'-'+uuid.uuid4().hex+'.json')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump({'source':source,'identity':identity,'content':content},f,ensure_ascii=False)
        f.flush(); os.fsync(f.fileno())
    return path
