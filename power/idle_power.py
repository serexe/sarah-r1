#!/usr/bin/python3
"""R1-only idle lease. No network listener, command payload, or forced suspend.
Private app journal is untrusted data. Privileged state is helper-owned.
"""
import ctypes
import fcntl
import json
import math
import os
import pwd
import re
import signal
import stat
import subprocess
import time

IDLE = 3600
BUSY = 300  # hard per-operation cap, never renewed by polls or duplicate begin
DEVICE_USER = os.getenv('R1_DEVICE_USER', 'phablet')  # Ubuntu Touch platform account
EVENTS = os.getenv('R1_POWER_EVENTS', '/home/' + DEVICE_USER + '/.local/share/hermes-touch-voice.local/power-events.json')
STATE = '/var/lib/r1-idle-power/state.json'


class Policy:
    def __init__(self, boot, saved=None):
        self.boot = boot
        self.deadline = 0
        self.busy = ''
        self.busy_until = 0
        self.cursors = {}
        self.highwater = -1
        if isinstance(saved, dict) and saved.get('boot') == boot:
            try:
                deadline = float(saved['deadline'])
                busy_until = float(saved['busy_until'])
                highwater = float(saved['highwater'])
                if not all(math.isfinite(x) for x in (deadline, busy_until, highwater)):
                    return
                if not isinstance(saved['busy'], str) or not isinstance(saved['cursors'], dict) or len(saved['cursors']) > 32:
                    return
                if any(not isinstance(k, str) or type(v) is not int for k, v in saved['cursors'].items()):
                    return
                self.deadline, self.busy_until, self.highwater = deadline, busy_until, highwater
                self.busy, self.cursors = saved['busy'], saved['cursors']
            except (KeyError, ValueError, TypeError):
                pass  # corrupt persisted state fails closed; no fresh boot lease

    def dump(self):
        return dict(boot=self.boot, deadline=self.deadline, busy=self.busy,
                    busy_until=self.busy_until, cursors=self.cursors, highwater=self.highwater)

    def held(self, now):
        return now < max(self.deadline, self.busy_until if self.busy else 0)

    def event(self, kind, at, op, now):
        if not isinstance(at, (int, float)) or not math.isfinite(at) or not 0 <= now-at <= 5:
            return False
        if kind == 'input':
            self.deadline = at + IDLE
            return True
        if kind == 'begin' and self.busy and at >= self.busy_until:
            if op == self.busy:
                return False
            self.busy, self.busy_until = '', 0
        if kind == 'begin' and op and at < self.deadline and not self.busy:
            self.busy, self.busy_until = op, at + BUSY
            return True
        if kind in ('end', 'cancel') and op and op == self.busy:
            fresh = at < self.busy_until
            self.busy, self.busy_until = '', 0
            if fresh:
                self.deadline = at + IDLE
            return fresh
        return False

    def consume(self, obj, now):
        if not isinstance(obj, dict) or set(obj) != {'boot', 'session', 'events'} or obj['boot'] != self.boot:
            return False
        session, events = obj['session'], obj['events']
        if not isinstance(session, str) or not re.fullmatch('[0-9a-f]{32}', session):
            return False
        if not isinstance(events, list) or len(events) > 32:
            return False
        changed = False
        for e in events:
            if not isinstance(e, dict) or set(e) != {'seq', 'at', 'kind', 'op'}:
                continue
            seq, at, kind, op = e['seq'], e['at'], e['kind'], e['op']
            if type(seq) is not int or seq <= self.cursors.get(session, 0):
                continue
            if not isinstance(at, (int, float)) or not math.isfinite(at) or at < self.highwater or not 0 <= now-at <= 5:
                continue
            if at == self.highwater and session not in self.cursors:
                continue
            if kind not in ('input', 'begin', 'end', 'cancel') or not isinstance(op, str) or len(op) > 64:
                continue
            self.cursors[session] = seq
            self.highwater = at
            # High-water timestamp prevents replay after old session cursor eviction.
            if len(self.cursors) > 32:
                del self.cursors[next(iter(self.cursors))]
            self.event(kind, at, op, now)
            changed = True
        return changed


def read_private(path, uid):
    """No symlink traversal, bounded regular private file; no root read gadget."""
    parts = path.split('/')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            s = os.fstat(leaf)
            if not stat.S_ISREG(s.st_mode) or s.st_uid != uid or stat.S_IMODE(s.st_mode) != 0o600 or s.st_size > 16384:
                raise ValueError('invalid private event file')
            raw = os.read(leaf, 16385)
            if len(raw) > 16384:
                raise ValueError('oversize journal')
            return json.loads(raw)
        finally:
            os.close(leaf)
    finally:
        os.close(fd)


def child_death_signal():
    parent = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0 or os.getppid() != parent:
        os._exit(1)


def spawn_hold():
    return subprocess.Popen(['/usr/sbin/powerd-cli', 'active'], stdin=subprocess.DEVNULL,
                            close_fds=True, preexec_fn=child_death_signal)


class Holder:
    def __init__(self, spawn=spawn_hold):
        self.spawn, self.child = spawn, None

    def sync(self, wanted):
        if self.child and self.child.poll() is not None:
            self.child = None
        if wanted and self.child is None:
            self.child = self.spawn()
        if not wanted and self.child is not None:
            self.child.terminate()
            try:
                self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait()
            self.child = None


def save(policy):
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf8') as f:
        os.chmod(tmp, 0o600)
        json.dump(policy.dump(), f, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE)
    d = os.open(os.path.dirname(STATE), os.O_DIRECTORY)
    try:
        os.fsync(d)
    finally:
        os.close(d)


def main():
    os.umask(0o077)
    os.makedirs(os.path.dirname(STATE), mode=0o700, exist_ok=True)
    lock = open(os.path.dirname(STATE) + '/owner.lock', 'w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    boot = open('/proc/sys/kernel/random/boot_id').read().strip()
    try:
        saved = json.load(open(STATE))
    except (OSError, ValueError):
        saved = None
    policy = Policy(boot, saved)
    uid = pwd.getpwnam(DEVICE_USER).pw_uid
    holder = Holder()
    last_wanted = None
    def stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            now = time.clock_gettime(time.CLOCK_BOOTTIME)
            changed = False
            try:
                changed = policy.consume(read_private(EVENTS, uid), now)
            except (OSError, ValueError, TypeError):
                pass  # malformed/unavailable journal never renews lease
            if changed:
                save(policy)  # persistence failure exits; NEVER acquire unpersisted lease
            wanted = policy.held(now)
            holder.sync(wanted)
            if wanted != last_wanted:
                print('r1-idle-power held=%s boottime=%.3f deadline=%.3f busy_until=%.3f' %
                      (wanted, now, policy.deadline, policy.busy_until), flush=True)
                last_wanted = wanted
            time.sleep(0.25)  # helper outside click cgroup; no app timer dependence
    finally:
        holder.sync(False)


if __name__ == '__main__':
    main()
