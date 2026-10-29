"""Narrow companion durable state; no provider or HA credentials here."""
import hashlib
import hmac
import io
import json
import re
import secrets
import sqlite3
import wave
from pathlib import Path

class Denied(ValueError):pass
class Conflict(ValueError):pass

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)

def ident(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise Denied('invalid_identifier')
    return value

def validate_audio(data):
    if not 44 <= len(data) <= 4*1024*1024:raise Denied('audio_size')
    try:
        with wave.open(io.BytesIO(data),'rb') as w:
            if w.getcomptype()!='NONE' or w.getsampwidth()!=2 or w.getnchannels() not in (1,2) or w.getframerate() not in (16000,44100,48000):raise Denied('audio_format')
            duration=w.getnframes()/w.getframerate()
            if not 0.25 <= duration <= 30:raise Denied('audio_duration')
            if len(w.readframes(w.getnframes())) != w.getnframes()*w.getsampwidth()*w.getnchannels():raise Denied('truncated_audio')
            return duration
    except (wave.Error,EOFError):raise Denied('invalid_wav') from None

class BlockedHermes:
    """Intentional closed seam. Not a simulated working Hermes integration.

    Existing /v1/runs cannot prove Codex-only fallback suppression and a
    companion-specific dispatch policy. There is NO enable/unsafe override.
    """
    ready=False
    reason='hermes_ingress_security_extension_required'
    def submit(self,*args,**kwargs):raise Denied(self.reason)

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,isolation_level=None,timeout=10)
        self.path.chmod(0o600); self.db.row_factory=sqlite3.Row
        self.db.executescript('''PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, device TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, device TEXT NOT NULL, conversation TEXT NOT NULL, request TEXT NOT NULL, fingerprint TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', transcript TEXT NOT NULL DEFAULT '', UNIQUE(device,request));
        CREATE TABLE IF NOT EXISTS approvals(nonce TEXT PRIMARY KEY, device TEXT NOT NULL, turn TEXT NOT NULL, action TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS dispatches(device TEXT NOT NULL, turn TEXT NOT NULL, conversation TEXT NOT NULL, action TEXT NOT NULL, PRIMARY KEY(device,turn,action));
        ''')
    def close(self):self.db.close()
    def provision(self,device,token):
        ident(device)
        if len(token)<40:raise Denied('weak_token')
        self.db.execute('INSERT INTO devices(id,digest) VALUES(?,?)',(device,hashlib.sha256(token.encode()).hexdigest()))
    def authenticate(self,token):
        if not token or len(token)>256:raise Denied('unauthorized')
        digest=hashlib.sha256(token.encode()).hexdigest()
        row=self.db.execute('SELECT id,digest FROM devices WHERE digest=? AND revoked=0',(digest,)).fetchone()
        if not row or not hmac.compare_digest(row['digest'],digest):raise Denied('unauthorized')
        return row['id']
    def revoke(self,device):self.db.execute('UPDATE devices SET revoked=1 WHERE id=?',(device,))
    def conversation(self,device):
        value=secrets.token_hex(16)
        self.db.execute('INSERT INTO conversations VALUES(?,?)',(value,device));return value
    def own(self,device,conversation):
        ident(conversation)
        if not self.db.execute('SELECT 1 FROM conversations WHERE id=? AND device=?',(conversation,device)).fetchone():raise Denied('not_found')
    def admit(self,device,conversation,request,fingerprint):
        ident(request);self.own(device,conversation)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.db.execute('SELECT * FROM turns WHERE device=? AND request=?',(device,request)).fetchone()
            if row:
                if row['conversation']!=conversation or row['fingerprint']!=fingerprint:raise Conflict('idempotency_key_conflict')
                result=row['id']
            else:
                if self.db.execute("SELECT 1 FROM turns WHERE conversation=? AND state NOT IN ('done','error','cancelled')",(conversation,)).fetchone():raise Conflict('conversation_busy_or_uncertain')
                result=secrets.token_hex(16)
                self.db.execute("INSERT INTO turns(id,device,conversation,request,fingerprint,state) VALUES(?,?,?,?,?,'transcribing')",(result,device,conversation,request,fingerprint))
            self.db.execute('COMMIT');return result
        except BaseException:self.db.execute('ROLLBACK');raise
    def get(self,device,turn):
        ident(turn)
        row=self.db.execute('SELECT id,conversation,state,detail,transcript FROM turns WHERE id=? AND device=?',(turn,device)).fetchone()
        if not row:raise Denied('not_found')
        return dict(row)
    def by_request(self,device,request):
        ident(request)
        row=self.db.execute('SELECT id,conversation,state,detail,transcript FROM turns WHERE device=? AND request=?',(device,request)).fetchone()
        if not row:raise Denied('not_found')
        return dict(row)
    def finish(self,device,turn,state,detail,transcript=''):
        self.get(device,turn)
        if state not in ('thinking','confirming','acting','speaking','done','error'):raise Denied('invalid_state')
        self.db.execute("UPDATE turns SET state=?,detail=?,transcript=? WHERE id=? AND device=? AND state NOT IN ('cancelled','uncertain','done','error')",(state,detail,transcript,turn,device))
    def cancel(self,device,turn,*,dispatch_pending=False):
        self.get(device,turn)
        state='uncertain' if dispatch_pending else 'cancelled'
        detail=('Stopped during dispatch. Action outcome unknown. No automatic retry; reconciliation required.' if dispatch_pending else 'Cancelled locally. Does not undo already dispatched actions.')
        self.db.execute("UPDATE turns SET state=?, detail=? WHERE id=? AND state NOT IN ('done','error','uncertain')",(state,detail,turn))
        return self.get(device,turn)
    def recover(self):
        self.db.execute("UPDATE turns SET state='uncertain',detail='Interrupted. No automatic redispatch; reconciliation required.' WHERE state NOT IN ('done','error','cancelled','uncertain')")
    def claim_dispatch(self,device,turn,conversation,action):
        """Atomic durable per-turn action claim. Commit BEFORE network dispatch.

        A crash after this claim is uncertain, never permission to replay.
        """
        self.db.execute('BEGIN IMMEDIATE')
        try:
            row=self.get(device,turn)
            self.own(device,conversation)
            if row['conversation']!=conversation or row['state'] in ('done','error','cancelled','uncertain'):
                raise Denied('turn_not_active')
            result=self.db.execute('INSERT OR IGNORE INTO dispatches VALUES(?,?,?,?)',
                                   (device,turn,conversation,canonical(action)))
            if result.rowcount!=1:
                self.db.execute('COMMIT');return False
            self.db.execute("UPDATE turns SET state='acting',detail='Dispatching authorized routine action' WHERE id=? AND device=?",(turn,device))
            self.db.execute('COMMIT');return True
        except BaseException:
            self.db.execute('ROLLBACK');raise
    def offer(self,device,turn,action,now):
        self.get(device,turn)
        nonce=secrets.token_hex(32)
        result=self.db.execute("INSERT INTO approvals SELECT ?,?,?,?,?,0 WHERE EXISTS (SELECT 1 FROM turns WHERE id=? AND device=? AND state NOT IN ('done','error','cancelled','uncertain'))",(nonce,device,turn,canonical(action),now+60,turn,device))
        if result.rowcount!=1:raise Denied('turn_not_active')
        return nonce
    def claim(self,device,turn,nonce,action,now):
        self.get(device,turn)
        result=self.db.execute("UPDATE approvals SET used=1 WHERE nonce=? AND device=? AND turn=? AND action=? AND expires>? AND used=0 AND EXISTS (SELECT 1 FROM turns WHERE id=? AND device=? AND state NOT IN ('done','error','cancelled','uncertain'))",(nonce,device,turn,canonical(action),now,turn,device))
        if result.rowcount!=1:raise Denied('confirmation_invalid_expired_or_replayed')
