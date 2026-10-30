"""Private TLS companion. Codex pool + local STT/TTS + opt-in exact HA."""
import argparse
import asyncio
import hashlib
import json
import ssl
import time
from collections import defaultdict, deque
from pathlib import Path
from aiohttp import web
from .core import BlockedHermes, Conflict, Denied, Store, validate_audio, canonical


def make_app(store, adapter=None, ha=None, siyuan=None, calendar=None, tvtime=None):
    adapter = adapter or BlockedHermes()
    buckets=defaultdict(deque); tasks={}; confirmations={}; dispatching=set()
    media=store.path.parent/'media'; media.mkdir(mode=0o700, exist_ok=True);media.chmod(0o700)
    @web.middleware
    async def guard(request,handler):
        try:
            auth=request.headers.get('Authorization','')
            if not auth.startswith('Bearer '):raise Denied('unauthorized')
            device=store.authenticate(auth[7:])
            q=buckets[device];now=time.monotonic()
            while q and q[0]<now-60:q.popleft()
            if len(q)>=90:return web.json_response({'error':'rate_limited'},status=429)
            q.append(now);request['device']=device
            response=await handler(request)
        except Denied as e:response=web.json_response({'error':str(e)},status=403)
        except Conflict as e:response=web.json_response({'error':str(e)},status=409)
        except (json.JSONDecodeError,UnicodeDecodeError,TypeError,KeyError):response=web.json_response({'error':'invalid_request'},status=400)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
    app=web.Application(client_max_size=4*1024*1024,middlewares=[guard])
    async def body(request,keys):
        value=await request.json()
        if not isinstance(value,dict) or set(value)!=set(keys):raise Denied('unexpected_fields')
        return value
    async def health(request):
        reason='Codex voice conversation with full Home Assistant tools on every turn; model interprets natural language and conversation context. Discover actual entities, room groups, detailed state and services across all HA domains. Requested services run without repeated routine approval or entity/action authorization gates. Group outcomes require discovered unchanged membership and every member readback. Accepted services are not automatically verified; uncertain outcomes never auto-retried. No shell or arbitrary network tool.' if ha is not None else getattr(adapter,'reason','')
        if siyuan is not None: reason+=' SiYuan discovery/search/read/create/stable-ID update/append/edit and exact childless document deletion; writes verified by readback, deletion locally backed up. Private and root zArchive excluded.'
        if calendar is not None: reason+=' Calendar enabled for explicitly configured scope; list/read/create/update/exact delete with readback. Configuration is not live scope verification.'
        if tvtime is not None: reason+=' TV time ON uses existing canonical workflow once; webhook accepted is not device readiness proof.'
        if getattr(adapter,'backend',None)=='acp': reason=adapter.reason+' Existing HA/SiYuan/calendar/TV grants preserved; server-owned mutation receipts, not model completion, establish action outcomes.'
        return web.json_response({'connected':True,'ready':bool(adapter.ready),'reason':reason,'protocol':1,'tools':bool(adapter.ready) and any(b is not None for b in (ha,siyuan,calendar,tvtime)),'home_assistant':ha is not None,'siyuan':siyuan is not None,'calendar':calendar is not None,'tvtime':tvtime is not None})
    async def conversation(request):
        await body(request,[])
        return web.json_response({'conversation':store.conversation(request['device'])},status=201)
    def active(device,turn):return store.get(device,turn)['state'] not in ('done','error','cancelled','uncertain')
    async def transcribe(clip):
        # Cancelling to_thread's await does not stop native STT. Keep the real
        # worker, clip and admission slot owned until the thread has finished.
        worker=asyncio.create_task(asyncio.to_thread(adapter.transcribe,clip))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            while not worker.done():
                try: await asyncio.shield(worker)
                except asyncio.CancelledError: pass
                except Exception: break
            if not worker.cancelled(): worker.exception()
            raise
    def released(device,turn,clip,task):
        # Also runs if Stop wins before execute's first instruction.
        clip.unlink(missing_ok=True);tasks.pop(turn,None);confirmations.pop(turn,None)
        if store.get(device,turn)['state']!='done':(media/(turn+'.mp3')).unlink(missing_ok=True)
    async def execute(device,turn,clip):
        transcript=''
        try:
            transcript=await transcribe(clip)
            if not active(device,turn):return
            store.finish(device,turn,'thinking','S.A.R.A.H is thinking.',transcript)
            conversation=store.get(device,turn)['conversation']
            rows=store.db.execute("SELECT transcript,detail FROM turns WHERE device=? AND conversation=? AND state='done' ORDER BY rowid DESC LIMIT 4",(device,conversation)).fetchall()
            history=[]
            for row in reversed(rows):history.extend([{'role':'user','content':row['transcript']},{'role':'assistant','content':row['detail']}])
            async def confirm(action):
                binding={'conversation':conversation,'action':action}
                digest=hashlib.sha256(canonical(binding).encode()).hexdigest()
                nonce=store.offer(device,turn,binding,time.time())
                future=asyncio.get_running_loop().create_future()
                envelope={'conversation':conversation,'nonce':nonce,'action_hash':digest,'expires':time.time()+60,
                          'label':action['arguments']['entity_id']+' '+action['arguments']['service']}
                confirmations[turn]=(device,binding,envelope,future)
                store.finish(device,turn,'confirming','Confirm exact routine action on screen',transcript)
                try:
                    accepted=await asyncio.wait_for(future,60)
                    permitted=accepted and active(device,turn)
                    if active(device,turn): store.finish(device,turn,'acting' if permitted else 'thinking','Dispatching confirmed routine action' if permitted else 'Action denied. Preparing reply.',transcript)
                    return permitted
                except TimeoutError:
                    if active(device,turn): store.finish(device,turn,'thinking','Confirmation expired. Nothing dispatched.',transcript)
                    return False
                finally: confirmations.pop(turn,None)
            outcomes=[]; read_results=[]
            async def dispatch(name,args):
                if not active(device,turn): return {'reply':'Request cancelled. Nothing further dispatched.'}
                async def claim(action):
                    if not active(device,turn): return False
                    # New note/calendar mutations consume one durable turn slot,
                    # even if a model changes arguments after an uncertain result.
                    if store.db.execute('SELECT 1 FROM dispatches WHERE device=? AND turn=? LIMIT 1',(device,turn)).fetchone(): return False
                    claimed=store.claim_dispatch(device,turn,conversation,action)
                    if claimed: dispatching.add(turn)
                    return claimed
                backend=tvtime if name == 'tvtime_on' else siyuan if name.startswith('sy_') else calendar if name.startswith('calendar_') else ha
                try:
                    outcome=await backend.dispatch(name,args,claim) if backend is not None else {'reply':'Requested tool unavailable. Nothing dispatched.'}
                finally:
                    dispatching.discard(turn)
                # Snapshot actual dispatcher output before giving it to runtime.
                # Model text/JSON and runtime return values cannot add outcomes.
                if name in ('ha_list_entities','ha_get_state','ha_list_services','sy_list_notebooks','sy_search','sy_read','calendar_list','calendar_read'):
                    read_results.append(outcome)
                else:
                    outcomes.append(dict(outcome))
                return outcome
            # Every utterance reaches the model with the same supported tools.
            # Semantic intent belongs to Codex, not a local phrase classifier.
            if hasattr(adapter, 'reply_turn'):
                text=await adapter.reply_turn(transcript,history,device=device,conversation=conversation,
                                              dispatch=dispatch if any(b is not None for b in (ha,siyuan,calendar,tvtime)) else None)
            else:
                text=await adapter.reply(transcript,history,dispatch=dispatch) if any(b is not None for b in (ha,siyuan,calendar,tvtime)) else await adapter.reply(transcript,history)
            if not active(device,turn):return
            # Actual dispatch outcomes remain server-owned. With no tool outcome,
            # preserve conversation/clarification exactly; never invent an action
            # receipt or replace free conversation with a fixed no-outcome phrase.
            if outcomes:
                receipts=' '.join(o['reply'] for o in outcomes)
                # Action turns use server-owned narration, even with mixed reads.
                # Untrusted synthesis can contradict a receipt; appending cannot fix it.
                # Pure read/conversation turns retain natural model prose unchanged.
                text=receipts
            errors=[o['reply'] for o in read_results if o.get('error')]
            if errors:text+='\n'+' '.join(errors)
            store.finish(device,turn,'speaking','Preparing spoken reply',transcript)
            try:await asyncio.wait_for(adapter.speak(text,media/(turn+'.mp3')),timeout=45)
            except Exception:
                (media/(turn+'.mp3')).unlink(missing_ok=True)
                # Text remains usable when optional free TTS unavailable.
            if active(device,turn):store.finish(device,turn,'done',text,transcript)
        except Exception as e:
            # Never include raw upstream exceptions/tokens in device output.
            if active(device,turn):store.finish(device,turn,'error','Voice request failed ('+type(e).__name__+'). Any dispatched action outcome may be unknown; no automatic retry.',transcript)

    async def submit(request):
        if not adapter.ready:return web.json_response({'error':adapter.reason},status=503)
        if request.content_type!='audio/wav':raise Denied('audio_content_type')
        device=request['device'];conversation=request.headers.get('X-Conversation','');key=request.headers.get('Idempotency-Key','')
        store.own(device,conversation)
        data=await request.read();validate_audio(data)
        fingerprint=hashlib.sha256(data).hexdigest()
        existing=store.db.execute('SELECT id FROM turns WHERE device=? AND request=?',(device,key)).fetchone()
        if not existing and tasks:raise Conflict('voice_worker_busy')
        turn=store.admit(device,conversation,key,fingerprint)
        if not existing:
            clip=media/(turn+'.wav');clip.touch(mode=0o600,exist_ok=False);clip.write_bytes(data)
            task=asyncio.create_task(execute(device,turn,clip))
            tasks[turn]=task
            task.add_done_callback(lambda done, d=device, t=turn, c=clip: released(d,t,c,done))
        return web.json_response({'turn':turn},status=202)
    async def poll(request):
        turn=request.match_info['turn'];result=store.get(request['device'],turn)
        result['audio']=result['state']=='done' and (media/(turn+'.mp3')).is_file()
        if turn in confirmations: result['confirmation']=confirmations[turn][2]
        return web.json_response(result)
    async def confirmation(request):
        value=await body(request,['conversation','nonce','action_hash','accept'])
        turn=request.match_info['turn'];device=request['device'];store.get(device,turn)
        pending=confirmations.get(turn)
        if pending is None or not isinstance(value['accept'],bool): raise Denied('confirmation_unavailable')
        owner,binding,envelope,future=pending
        if owner!=device or any(value[k]!=envelope[k] for k in ('conversation','nonce','action_hash')) or future.done(): raise Denied('confirmation_binding_denied')
        store.claim(device,turn,value['nonce'],binding,time.time())
        future.set_result(value['accept'])
        return web.json_response({'accepted':value['accept']})
    async def lookup(request):
        # Read-only, authenticated device ownership; never admits or dispatches.
        result=store.by_request(request['device'],request.match_info['request'])
        result['audio']=result['state']=='done' and (media/(result['id']+'.mp3')).is_file()
        return web.json_response(result)
    async def audio(request):
        turn=request.match_info['turn'];row=store.get(request['device'],turn)
        path=media/(turn+'.mp3')
        if row['state']!='done' or not path.is_file():raise Denied('not_found')
        return web.Response(body=path.read_bytes(),content_type='audio/mpeg')
    async def cancel(request):
        await body(request,[])
        # Discard output; no retry/undo. Wake unconfirmed actions without dispatch.
        turn=request.match_info['turn'];result=store.cancel(request['device'],turn,dispatch_pending=turn in dispatching)
        pending=confirmations.get(turn)
        if pending and not pending[3].done(): pending[3].set_result(False)
        task=tasks.get(turn)
        if task is not None and not task.cancelling(): task.cancel()
        return web.json_response(result)
    async def cleanup(app):
        pending=list(tasks.values())
        for task in pending:
            if not task.cancelling(): task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
    app.on_cleanup.append(cleanup)
    app.router.add_get('/v1/health',health);app.router.add_post('/v1/conversations',conversation)
    app.router.add_get('/v1/requests/{request}',lookup)
    app.router.add_post('/v1/turns',submit);app.router.add_get('/v1/turns/{turn}',poll)
    app.router.add_get('/v1/turns/{turn}/audio',audio);app.router.add_post('/v1/turns/{turn}/cancel',cancel)
    app.router.add_post('/v1/turns/{turn}/confirmation',confirmation)
    return app

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,required=True);p.add_argument('--cert',required=True);p.add_argument('--key',required=True)
    p.add_argument('--hermes-source',type=Path,required=True)
    p.add_argument('--bind',default='127.0.0.1');p.add_argument('--port',type=int,default=8787)
    p.add_argument('--backend',choices=('codex','acp'),default='codex',
                   help='Manual backend selection; ACP requires reviewed dedicated Sarah profile')
    args=p.parse_args();store=Store(args.db);store.recover()
    from .acp_runtime import create_runtime
    adapter=create_runtime(store,args.hermes_source,args.backend)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(args.cert,args.key)
    from .ha import HADispatcher
    from .siyuan import SiYuanDispatcher
    from .calendar import CalendarDispatcher
    from .tvtime import TVTimeDispatcher
    web.run_app(make_app(store,adapter,HADispatcher.from_env(),SiYuanDispatcher.from_env(),CalendarDispatcher.from_env(),TVTimeDispatcher.from_env()),host=args.bind,port=args.port,ssl_context=tls,access_log=None)

if __name__=='__main__':main()
