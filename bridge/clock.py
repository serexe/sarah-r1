"""R1 clock presentation only; no general number rewriting."""
import re
import os
from datetime import datetime
from zoneinfo import ZoneInfo

TIMEZONE=os.getenv('R1_TIMEZONE', 'UTC')
CENTRAL=ZoneInfo(TIMEZONE)
_SMALL='zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
def words(n):
    return _SMALL[n] if n<20 else ['','','twenty','thirty','forty','fifty'][n//10]+(' '+_SMALL[n%10] if n%10 else '')
def clock(hour,minute):
    if minute==0 and hour in (0,12): return 'midnight' if hour==0 else 'noon'
    return words(hour%12 or 12)+(' oh '+words(minute) if 0<minute<10 else ' '+words(minute) if minute else '')+(' A M' if hour<12 else ' P M')

def central_event(event):
    result=dict(event)
    for key in ('start','end'):
        value=event.get(key,{})
        if value.get('dateTime'):
            dt=datetime.fromisoformat(value['dateTime'].replace('Z','+00:00'))
            if dt.tzinfo is not None:
                result[key]=dict(value,dateTime=dt.astimezone(CENTRAL).isoformat(),timeZone=TIMEZONE)
    return result

def event_confirmation(verb,event):
    title=event.get('summary') or 'event'
    start=event.get('start',{})
    if start.get('dateTime'):
        dt=datetime.fromisoformat(start['dateTime'].replace('Z','+00:00')).astimezone(CENTRAL)
        when=dt.strftime('%Y-%m-%d at ')+str(dt.hour%12 or 12)+dt.strftime(':%M %p')+' '+TIMEZONE
    else: when=start.get('date')
    return verb+' '+title+(' on '+when if when else '')+'.'

_H=r'(?:[01]?\d|2[0-3])'
_M=r'[0-5]\d'
_AP=r'([ap])\.?\s*m\.?'
def spoken_clocks(text):
    # ISO instants carry offset authority. Keep date, convert instant before speech.
    def iso(m):
        try:
            dt=datetime.fromisoformat(m.group().replace('Z','+00:00')).astimezone(CENTRAL)
            return dt.strftime('%Y-%m-%d')+' at '+clock(dt.hour,dt.minute)
        except ValueError: return m.group()
    text=re.sub(r'(?<![\w])\d{4}-\d{2}-\d{2}T'+_H+':'+_M+r'(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})(?![\w])',iso,text)
    # Shared meridiem ranges.
    def ranged(m):
        h1,n1,h2,n2,ap=m.groups()
        if not 1<=int(h1)<=12 or not 1<=int(h2)<=12: return m.group()
        offset=12 if ap.lower()=='p' else 0
        return clock(int(h1)%12+offset,int(n1))+' to '+clock(int(h2)%12+offset,int(n2))
    text=re.sub(r'(?<![\w:])('+_H+'):('+_M+r')\s*[–—-]\s*('+_H+'):('+_M+r')\s*'+_AP+r'(?!\w)',ranged,text,flags=re.I)
    def explicit(m):
        h,n,ap=m.groups()
        if not 1<=int(h)<=12: return m.group()
        # Plain PM. period belongs to sentence; dotted p.m. is abbreviation.
        suffix='.' if m.group().endswith('.') and m.group().count('.')==1 else ''
        return clock(int(h)%12+(12 if ap.lower()=='p' else 0),int(n or 0))+suffix
    text=re.sub(r'(?<![\w:])('+_H+r')(?::('+_M+r'))?\s*'+_AP+r'(?!\w)',explicit,text,flags=re.I)
    # Bare HH:MM only with explicit clock context, never arbitrary durations/ratios.
    text=re.sub(r'\b(at|from|until|to)\s+('+_H+'):('+_M+r')(?![\w:]|\s*(?:hours?|minutes?|seconds?))',lambda m:m[1]+' '+clock(int(m[2]),int(m[3])),text,flags=re.I)
    return re.sub(r'\bS\.A\.R\.A\.H', 'Sarah', text)
