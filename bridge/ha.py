"""Server-only Home Assistant REST tools. No entity/action authorization gate."""
import asyncio
import json
import math
import os
import re
from urllib.parse import urlsplit
import httpx
from .core import Denied

LIGHT_GUIDANCE = ('Discover actual entities and services with ha_list_entities and ha_list_services. '
    'Resolve rooms from actual friendly names, area metadata and group membership, not guessed bulb IDs. '
    'Prefer the discovered room group for room requests; do not substitute one bulb or all household lights. '
    'Clarify only genuinely ambiguous targets. Group success needs unchanged membership and every member readback.')


def tool(name, description, properties, required=()):
    return {'type':'function','name':name,'description':description,'strict':False,
            'parameters':{'type':'object','properties':properties,'required':list(required),'additionalProperties':False}}

TOOLS = [
    tool('ha_list_entities','Discover HA entities in any domain; optional domain and room/name filter. Returns actual state and attributes.',
         {'domain':{'type':'string'},'area':{'type':'string'}}),
    tool('ha_get_state','Read detailed actual HA entity state, attributes, timestamps and discovered group members.',
         {'entity_id':{'type':'string'}},['entity_id']),
    tool('ha_list_services','Discover available HA services and their parameter/target/response metadata; optional domain filter.',
         {'domain':{'type':'string'}}),
    tool('ha_call_service','Call any discovered HA domain/service without repeated routine approval. data is JSON service parameters; entity_id optional for services without entity targets. Readback is authoritative; accepted is not necessarily verified.',
         {'domain':{'type':'string'},'service':{'type':'string'},'entity_id':{'type':['string','null']},
          'data':{'type':['string','null'],'description':'JSON object of service data, e.g. {"temperature":22} or {"area_id":"lounge"}.'},
          'return_response':{'type':'boolean'}},['domain','service'])]


def identifier(value, entity=False):
    pattern = r'[a-z0-9_]+\.[a-z0-9_]+' if entity else r'[a-z0-9_]+'
    if not isinstance(value,str) or not re.fullmatch(pattern,value): raise Denied('ha_identifier_invalid')
    return value


def validate(name,args):
    if not isinstance(args,dict): raise Denied('ha_arguments_denied')
    clean = dict(args)
    if name == 'ha_get_state':
        if set(clean) != {'entity_id'}: raise Denied('ha_arguments_denied')
        identifier(clean['entity_id'],True)
    elif name in ('ha_list_entities','ha_list_services'):
        if set(clean) - ({'domain','area'} if name == 'ha_list_entities' else {'domain'}): raise Denied('ha_arguments_denied')
        clean = {k:v for k,v in clean.items() if v not in (None,'')}
        if 'domain' in clean: identifier(clean['domain'])
        if 'area' in clean and not isinstance(clean['area'],str): raise Denied('ha_arguments_denied')
    elif name == 'ha_call_service':
        if set(clean)-{'domain','service','entity_id','data','return_response'}: raise Denied('ha_arguments_denied')
        for key in ('domain','service'): identifier(clean.get(key))
        data = clean.get('data')
        if isinstance(data,str):
            try: data=json.loads(data)
            except ValueError: raise Denied('ha_data_invalid')
        if data is None: data={}
        if not isinstance(data,dict): raise Denied('ha_data_invalid')
        data=dict(data)
        entity=clean.get('entity_id')
        if entity is not None:
            identifier(entity,True)
            if 'entity_id' in data and data['entity_id'] != entity: raise Denied('ha_target_conflict')
            data['entity_id']=entity
        # Validate JSON, retaining genuine service parameters (including nulls).
        try: json.dumps(data,allow_nan=False)
        except (ValueError,TypeError): raise Denied('ha_data_invalid')
        response=clean.get('return_response',False)
        if type(response) is not bool: raise Denied('ha_arguments_denied')
        clean={'domain':clean['domain'],'service':clean['service'],'data':data,'return_response':response}
    else: raise Denied('ha_tool_denied')
    return {'name':name,'arguments':clean}


class HADispatcher:
    # Bound GET-only convergence, allowing Hue members and then group to settle.
    convergence_seconds = 5.0
    convergence_interval = 0.25

    def __init__(self,origin,token,allowed=()):
        u=urlsplit(origin)
        if u.scheme not in ('https','http') or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ('','/'):
            raise ValueError('ha_origin_denied')
        if not token: raise ValueError('ha_configuration_denied')
        # Legacy allowlist accepted for config compatibility, never authorization.
        self.origin,self.token=origin.rstrip('/'),token

    @classmethod
    def from_env(cls):
        if os.getenv('R1_ENABLE_HA') != '1' or not os.getenv('R1_HA_ORIGIN') or not os.getenv('R1_HA_TOKEN'): return None
        return cls(os.environ['R1_HA_ORIGIN'],os.environ['R1_HA_TOKEN'])

    async def _request(self,method,path,data=None):
        async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
            async with client.stream(method,self.origin+path,headers={'Authorization':'Bearer '+self.token},json=data) as response:
                if response.status_code != 200: raise RuntimeError('ha_http_'+str(response.status_code))
                raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>4*1024*1024: raise RuntimeError('ha_response_too_large')
                return json.loads(raw)

    async def _state(self,entity,details=False):
        identifier(entity,True)
        row=await self._request('GET','/api/states/'+entity)
        if not isinstance(row,dict) or row.get('entity_id') != entity or not isinstance(row.get('state'),str) or not isinstance(row.get('attributes',{}),dict):
            raise RuntimeError('ha_readback_invalid')
        return dict(row,observed=row['state'])

    @staticmethod
    def members(row):
        members=row.get('attributes',{}).get('entity_id')
        if members is None: return None
        if not isinstance(members,list) or not members or len(members)!=len(set(m for m in members if isinstance(m,str))):
            raise RuntimeError('ha_group_membership_invalid')
        for entity in members: identifier(entity,True)
        return members

    async def state(self,entity,details=False):
        row=await self._state(entity)
        members=self.members(row)
        if members is not None:
            row['members']=[]
            for member in members:
                try: observed=await self._state(member)
                except Exception: observed={'entity_id':member,'observed':'unknown','state':'unknown','attributes':{}}
                row['members'].append(observed)
        return row

    @staticmethod
    def partial_light_reply(before, observed, requested):
        """Narrate only actual group-member readbacks, never aggregate success."""
        if requested not in ('on','off') or not before or any(
                not entity.startswith('light.') or 'members' not in row for entity,row in before.items()):
            return None
        def label(row):
            return str(row.get('attributes',{}).get('friendly_name') or row['entity_id'].replace('_',' '))
        by_entity={row['entity_id']:row for row in observed}
        parts=[]
        for entity,prior in before.items():
            after=by_entity.get(entity)
            if after is None:
                parts.append("Couldn't read the updated state of "+label(prior)+'.')
                continue
            old=prior['attributes'].get('entity_id',[])
            new=after.get('attributes',{}).get('entity_id',[])
            members={row['entity_id']:row for row in after.get('members',[])}
            known={row['entity_id']:row for row in prior.get('members',[])}
            ids=list(dict.fromkeys([*old,*new]))
            confirmed=[e for e in ids if members.get(e,{}).get('observed')==requested]
            if confirmed:
                count=len(confirmed)
                parts.append(str(count)+(' light in ' if count==1 else ' lights in ')+label(after)+
                             (' is ' if count==1 else ' are ')+requested+'.')
            for member in ids:
                row=members.get(member)
                name=label(row if row and row.get('attributes',{}).get('friendly_name') else known.get(member,{'entity_id':member}))
                state=row.get('observed') if row else None
                if state==requested: continue
                if state=='unavailable': parts.append(name+" isn't responding.")
                elif state in ('on','off'): parts.append(name+' is still '+state+'.')
                else: parts.append("Couldn't read the state of "+name+'.')
            if set(old)!=set(new):
                parts.append('Group membership changed in '+label(after)+'; the original group could not be confirmed.')
            elif len(confirmed)==len(ids):
                parts.append(label(after)+' has not yet confirmed the full requested change.')
        return ' '.join(parts) or None

    async def dispatch(self,name,args,claim):
        dispatched=False
        before={}; requested=None
        try:
            action=validate(name,args); args=action['arguments']
            if name == 'ha_list_entities':
                rows=await self._request('GET','/api/states')
                if not isinstance(rows,list): raise RuntimeError('ha_discovery_invalid')
                domain=args.get('domain'); area=args.get('area','').casefold()
                rows=[row for row in rows if isinstance(row,dict) and isinstance(row.get('entity_id'),str)
                      and (not domain or row['entity_id'].startswith(domain+'.'))
                      and (not area or area in (row['entity_id']+' '+str(row.get('attributes',{}).get('friendly_name',''))+' '+str(row.get('attributes',{}).get('area_id',''))).replace('_',' ').casefold())]
                return {'entities':rows,'reply':json.dumps({'entities':rows})}
            if name == 'ha_get_state':
                result=await self.state(args['entity_id'])
                result['reply']=result['entity_id']+' is '+result['state']+'. '+json.dumps(result)
                if 'members' in result:
                    uniform=all(m['observed']==result['state'] and m['observed'] not in ('unknown','unavailable') for m in result['members'])
                    result['reply']+=' '+', '.join(m['entity_id']+'='+m['observed'] for m in result['members'])+('. Whole-room state verified.' if uniform else '. Whole-room state not verified.')
                return result
            services=await self._request('GET','/api/services')
            if not isinstance(services,list): raise RuntimeError('ha_discovery_invalid')
            if name == 'ha_list_services':
                rows=[s for s in services if not args.get('domain') or s.get('domain')==args['domain']]
                return {'services':rows,'reply':json.dumps({'services':rows})}
            meta=next((s.get('services',{}).get(args['service']) for s in services if s.get('domain')==args['domain']),None)
            if meta is None: raise Denied('ha_service_unavailable')
            service=args['service']; data=args['data']
            response=meta.get('response',{})
            required=isinstance(response,dict) and response.get('optional') is False
            returns=args['return_response'] or required
            # Effective response mode part of durable identity, not model syntax.
            action['arguments']['return_response']=returns
            targets=data.get('entity_id',[])
            if isinstance(targets,str): targets=[e.strip() for e in targets.split(',')]
            if not isinstance(targets,list): raise Denied('ha_target_invalid')
            targets=list(dict.fromkeys(targets))
            before={}
            for entity in targets:
                if entity == 'all': continue
                identifier(entity,True)
                before[entity]=await self.state(entity)
            if not await claim(action): return {'reply':'Action cancelled or already claimed. Nothing dispatched.','dispatched':False}
            dispatched=True
            result=await self._request('POST','/api/services/'+args['domain']+'/'+service+('?return_response' if returns else ''),data)
            observed=[]; verified=bool(before) and len(before)==len(targets)
            requested={'turn_on':'on','turn_off':'off','media_play':'playing','media_pause':'paused','media_stop':'idle'}.get(service)
            brightness=data.get('brightness_pct')
            if brightness is not None and service=='turn_on' and type(brightness) in (int,float): requested='off' if brightness==0 else 'on'
            try:
                async with asyncio.timeout(self.convergence_seconds):
                    while True:
                        observed=[]; verified=bool(before) and len(before)==len(targets)
                        for entity,prior in before.items():
                            after=await self.state(entity); observed.append(after)
                            matches=requested is not None and after['state']==requested
                            if service in ('media_next_track','media_previous_track'):
                                matches=after['state'] not in ('unknown','unavailable','off','idle') and any(
                                    after['attributes'].get(k) is not None and after['attributes'].get(k)!=prior['attributes'].get(k)
                                    for k in ('media_title','media_content_id'))
                            prior_members=self.members(prior); after_members=self.members(after)
                            if prior_members is not None or after_members is not None:
                                matches=matches and prior_members is not None and after_members is not None and set(prior_members)==set(after_members)
                                members=after.get('members',[])
                                matches=matches and bool(members) and {m['entity_id'] for m in members}==set(after_members or [])
                                matches=matches and all(m['observed']==requested and m['observed'] not in ('unknown','unavailable') for m in members)
                            if brightness is not None and requested=='on':
                                matches=matches and all(type(r.get('attributes',{}).get('brightness')) in (int,float) and
                                    math.isfinite(r['attributes']['brightness']) and abs(r['attributes']['brightness']-brightness*255/100)<=1
                                    for r in [after,*after.get('members',[])])
                            verified=verified and matches
                        if verified or not before or (requested is None and service not in ('media_next_track','media_previous_track')): break
                        await asyncio.sleep(self.convergence_interval)
            except TimeoutError:
                verified=False
            labels=', '.join(str(row.get('attributes',{}).get('friendly_name') or entity.replace('_',' ')) for entity,row in before.items()) or 'Home Assistant'
            summary=(labels+(' is '+requested+'.' if requested else ' changed.')+' State verified. Service accepted.' if verified else
                     labels+': service accepted. Outcome not verified. No automatic retry.')
            if not verified:
                summary=self.partial_light_reply(before,observed,requested) or summary
            return {'dispatched':True,'accepted':True,'verified':bool(verified),'states':observed,'result':result,'reply':summary}
        except Denied as e:
            return {'dispatched':dispatched,'verified':False,'error':str(e),'reply':('Home Assistant dispatch attempted. Outcome not verified. No automatic retry.' if dispatched else 'Home Assistant request denied: '+str(e)+'. Nothing dispatched.')}
        except Exception:
            if dispatched and 'observed' in locals():
                summary=self.partial_light_reply(before,[],requested)
                if summary: return {'dispatched':True,'verified':False,'reply':summary}
            return {'dispatched':dispatched,'verified':False,'reply':('Home Assistant dispatch attempted. Outcome not verified. No automatic retry.' if dispatched else 'Home Assistant discovery or preflight failed. Nothing dispatched.')}
