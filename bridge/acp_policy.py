"""Exact existing Sarah schemas and policy identity; no credential/config reads."""
import hashlib
import json
from pathlib import Path
from .ha import TOOLS as HA, LIGHT_GUIDANCE
from .siyuan import TOOLS as SY, GUIDANCE as SY_GUIDANCE
from .calendar import TOOLS as CAL, GUIDANCE as CAL_GUIDANCE
from .tvtime import TOOLS as TV, GUIDANCE as TV_GUIDANCE

TOOLS = HA + SY + CAL + TV
NAMES = frozenset(t['name'] for t in TOOLS)
def normalized(value):
    if isinstance(value, list): return [normalized(v) for v in value]
    if not isinstance(value, dict): return value
    result = {k: normalized(v) for k, v in value.items() if not (k == 'required' and v == [])}
    if result.pop('nullable', False): result['type'] = [result['type'], 'null']
    return result

TOOLSET = 'sarah_bridge'
SCHEMAS = [{'type': 'function', 'function': {k: t[k] for k in ('name', 'description', 'parameters')}} for t in TOOLS]
GUIDANCE = ('You are S.A.R.A.H, pronounced Sarah, your R1 voice companion. Reply briefly. '
            'Only supplied bridge tools exist. Never claim action success from agent completion; '
            'only actual server receipts establish outcomes. Never retry uncertain writes. '
            + LIGHT_GUIDANCE + ' ' + SY_GUIDANCE + ' ' + CAL_GUIDANCE + ' ' + TV_GUIDANCE)

def identity():
    root = Path(__file__).parent
    files = ['acp_policy.py', 'acp_launcher.py', 'acp_client.py', 'acp_runtime.py',
             'ha.py', 'siyuan.py', 'calendar.py', 'tvtime.py', 'sarah-acp.yaml',
             'server.py', 'core.py']
    payload = {'version': 1, 'schemas': SCHEMAS,
               'files': {f: hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

def validate(name, args):
    if name not in NAMES or not isinstance(args, dict):
        raise ValueError('acp_scoped_tool_denied')
    schema = next(t['parameters'] for t in TOOLS if t['name'] == name)
    if set(args) - set(schema['properties']) or set(schema['required']) - set(args):
        raise ValueError('acp_scoped_arguments_denied')
    return args
