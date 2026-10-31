"""Strict opt-in diagnostics. No raw payload written before validation. No public lookup."""
import json, re, secrets, sqlite3, time, os
from pathlib import Path
from aiohttp import web
PHASES=set('disconnected ready done error cancelled uncertain recording finalizing uploading polling playing reply_audio_pending confirming creating cancelling other'.split())
BASE={'schema','appVersion','phase','serverError','httpStatus','audioNext','chunkInFlight'}
FIELDS=BASE|{k+s for k in ('request','turn','conversation') for s in ('Present','Length','Hash')}
class Invalid(ValueError):pass
class Quota(Exception):pass
def validate(p):
    if type(p) is not dict or set(p)!=FIELDS:raise Invalid()
    for k,lo,hi in [('schema',1,1),('appVersion',1,999999),('httpStatus',0,599),('audioNext',0,32)]:
        if type(p[k]) is not int or not lo<=p[k]<=hi:raise Invalid()
    if p['httpStatus']!=0 and p['httpStatus']<100:raise Invalid()
    if type(p['phase']) is not str or p['phase'] not in PHASES:raise Invalid()
    if type(p['serverError']) is not str or p['serverError'] not in {'none','unauthorized','not_found','invalid_identifier','other'}:raise Invalid()
    if type(p['chunkInFlight']) is not bool:raise Invalid()
    for k in ('request','turn','conversation'):
        present,n,h=p[k+'Present'],p[k+'Length'],p[k+'Hash']
        if type(present) is not bool or type(n) is not int or not 0<=n<=65535 or type(h) is not str:raise Invalid()
        if present:
            if re.fullmatch('[0-9a-f]{12}',h) is None:raise Invalid()
        elif n!=0 or h!='':raise Invalid()
    return json.dumps(p,sort_keys=True,separators=(',',':'))
def unique_pairs(pairs):
    result={}
    for k,v in pairs:
        if k in result:raise Invalid()
        result[k]=v
    return result
class Reports:
    def __init__(self, parent):
        self.parent=Path(parent)/'diagnostics'
    def connect(self):
        self.parent.mkdir(mode=0o700,exist_ok=True);self.parent.chmod(0o700)
        path=self.parent/'reports.sqlite3'
        fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);os.close(fd);path.chmod(0o600)
        db=sqlite3.connect(path)
        db.execute('CREATE TABLE IF NOT EXISTS reports(code TEXT PRIMARY KEY,owner TEXT NOT NULL,created INTEGER NOT NULL,payload TEXT NOT NULL)')
        return db
    def submit(self,owner,p,now=None):
        encoded=validate(p);now=int(time.time() if now is None else now)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM reports WHERE created < ?', (now-7*86400,))
            if db.execute('SELECT count(*) FROM reports WHERE owner=? AND created>?',(owner,now-3600)).fetchone()[0]>=5:raise Quota()
            # Absolute global bound plus per-device 20; oldest diagnostic reports only.
            db.execute('DELETE FROM reports WHERE code IN (SELECT code FROM reports WHERE owner=? ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 19)',(owner,))
            db.execute('DELETE FROM reports WHERE code IN (SELECT code FROM reports ORDER BY created DESC,rowid DESC LIMIT -1 OFFSET 999)')
            code=secrets.token_hex(12).upper()
            db.execute('INSERT INTO reports VALUES(?,?,?,?)',(code,owner,now,encoded))
        return code
    def get(self,owner,code):
        if re.fullmatch('[A-F0-9]{24}',code) is None:return None
        with self.connect() as db:
            row=db.execute('SELECT created,payload FROM reports WHERE owner=? AND code=? AND created>=?',(owner,code,int(time.time())-7*86400)).fetchone()
        return None if row is None else {'receipt':code,'createdUtcEpoch':row[0],'report':json.loads(row[1])}
def install(app,parent):
    reports=Reports(parent)
    async def submit(request):
        # Existing server guard already authenticated request['device']; never request ownership lookup.
        if request.content_type!='application/json' or request.headers.get('Content-Encoding','identity')!='identity':return web.json_response({'error':'invalid_diagnostics'},status=400)
        if request.content_length is not None and request.content_length>8192:return web.json_response({'error':'diagnostics_too_large'},status=413)
        data=bytearray()
        async for chunk in request.content.iter_chunked(1024):
            data.extend(chunk)
            if len(data)>8192:return web.json_response({'error':'diagnostics_too_large'},status=413)
        try:
            p=json.loads(data.decode('utf8'),object_pairs_hook=unique_pairs,parse_constant=lambda _: (_ for _ in ()).throw(Invalid()))
            code=reports.submit(request['device'],p)
        except (Invalid,ValueError,TypeError,UnicodeError):return web.json_response({'error':'invalid_diagnostics'},status=400)
        except Quota:return web.json_response({'error':'diagnostic_quota'},status=429)
        except (OSError,sqlite3.Error):return web.json_response({'error':'diagnostic_unavailable'},status=503)
        return web.json_response({'receipt':code},status=201)
    async def lookup(request):
        try:result=reports.get(request['device'],request.match_info['code'])
        except (OSError,sqlite3.Error):return web.json_response({'error':'diagnostic_unavailable'},status=503)
        return web.json_response(result if result is not None else {'error':'not_found'},status=200 if result else 404)
    app.router.add_post('/v1/diagnostics',submit)
    app.router.add_get('/v1/diagnostics/{code}',lookup)
