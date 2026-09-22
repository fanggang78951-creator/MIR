"""Bounded LFM2 control-flow model, not an engine or an in-game acceptance test.

Unique-label CALL/BREAK return and host-local GOTO reflect the 2026-09-08
fixed engine probe. This model does not grant arbitrary import/engine semantics.
#IF begins a new flat condition; there is no Python-like nested #IF scope.
Unknown active actions/conditions fail closed. RNG choices are injected; generated
random selector code, item writes, timers and busy state are never mocked out.
"""
from copy import deepcopy
import heapq
import re


class ScriptModel:
    def __init__(self, programs, chance=None, movr=None):
        self.programs = {}
        for name, text in programs.items():
            labels = {}
            for match in re.finditer(r'(?m)^\[@([^\]]+)\]\s*$', text):
                end = re.search(r'(?m)^\[@', text[match.end():])
                labels[match[1]] = text[match.end():match.end()+end.start() if end else len(text)].splitlines()
            self.programs[name] = labels
        self.state = {}; self.gold = 10000
        self.items = {box: {'NAME':'测试装备','HDC':20,'HMC':20,'HSC':20,'rows':{},'abil':{},'native':{},'stars':0} for box in (27,28)}
        self.events=[]; self.queue=[]; self.time=0; self.sequence=0; self.steps=0
        self.chance=chance or (lambda name,label,cmd,args: False if cmd=='RANDOM' or args==['1','1000'] else True)
        self.movr=movr or (lambda variable,low,high: low)

    def value(self, text):
        text=re.sub(r'<\$STR\(([^)]+)\)>',lambda m:str(self.state.get(m[1],'' if m[1].startswith('S$') else 0)),text,flags=re.I)
        text=re.sub(r'<\$BOXITEM\[(\d+)\]\.([^>]+)>',lambda m:str(self.items[int(m[1])].get(m[2].upper(),'')),text,flags=re.I)
        if text.startswith(('N$','S$')): return self.state.get(text,'' if text.startswith('S$') else 0)
        try: return int(text)
        except ValueError: return text

    def condition(self,name,label,cmd,args):
        if cmd=='NOT': return not self.condition(name,label,args[0].upper(),args[1:])
        if cmd in ('RANDOM','RANDOMEX'): return self.chance(name,label,cmd,[str(self.value(arg)) for arg in args])
        if cmd=='CHECKGAMEGOLD':
            assert args[0]=='>';return self.gold>self.value(args[1])
        if cmd=='CHECKCONTAINSTEXT': return str(self.value(args[1])) in str(self.value(args[0]))
        a=self.value(args[0]); b=self.value(args[1]) if len(args)>1 else ''
        if cmd=='EQUAL': return a==b
        if cmd=='LARGE': return a>b
        if cmd=='SMALL': return a<b
        raise AssertionError(('unsupported condition',cmd,args))

    def execute(self,name,label,depth=0,host=None):
        host = name if host is None else host
        assert depth<100,'unbounded GOTO recursion'
        assert label in self.programs[name],(name,label)
        active=False; mode='none'; matched=True
        for raw in self.programs[name][label]:
            line=raw.strip()
            if not line or line.startswith(';') or line in ('{','}'): continue
            self.steps+=1; assert self.steps<100000,'unbounded script execution'
            words=line.split();cmd=words[0].upper();args=words[1:]
            if cmd=='#IF': matched=True;active=False;mode='condition';continue
            if cmd=='#ACT': active=matched;mode='action';continue
            if cmd=='#ELSEACT': active=not matched;mode='action';continue
            if cmd=='#SAY': mode='say';continue
            if mode=='condition':
                # Preserve short-circuit conditions: blocked branches do not draw RNG.
                matched=matched and self.condition(name,label,cmd,args);continue
            if mode!='action' or not active: continue
            self.events.append((self.time,name,label,cmd,tuple(args)))
            if cmd in ('BREAK','RETURN'): return
            if cmd=='GOTO': self.execute(host,args[0].lstrip('@'),depth+1,host=host)
            elif cmd=='#CALL': self.execute(args[0].strip('[]').replace('\\','/').split('/')[-1],args[1].lstrip('@'),depth+1,host=host)
            elif cmd=='DELAYGOTO':
                self.sequence+=1;heapq.heappush(self.queue,(self.time+int(args[0]),self.sequence,name,args[1].lstrip('@')))
            elif cmd=='MOV': self.state[args[0]]=self.value(' '.join(args[1:]))
            elif cmd in ('INC','DEC'): self.state[args[0]]=self.state.get(args[0],0)+(1 if cmd=='INC' else -1)*int(self.value(args[1]))
            elif cmd=='MOVR': self.state[args[0]]=self.movr(args[0],int(self.value(args[1])),int(self.value(args[2])))
            elif cmd=='FORMULATION':
                expr=str(self.value(args[0])); assert re.fullmatch(r'[0-9 +*/().-]+',expr),expr
                self.state[args[1]]=int(eval(expr,{'__builtins__':{}},{}))
            elif cmd=='GAMEGOLD': assert args[0]=='-';self.gold-=int(args[1])
            elif cmd=='GETCUSTOMITEMTEXT':
                box=int(args[0].lower().replace('boxitem',''))
                variable=re.fullmatch(r'<\$STR\(([^)]+)\)>',args[1],re.I)[1]
                self.state[variable]=self.items[box].get('text','')
            elif cmd.startswith('SETCUSTOMITEM') or cmd in ('SETNEWITEMVALUE','CHANGEITEMUPGRADECOUNT','UPDATEITEM','RETURNBOXITEM'):
                box=int(args[0].lower().replace('boxitem',''));item=self.items[box]
                if cmd=='SETCUSTOMITEMTEXT': item['text']=self.value(' '.join(args[1:]))
                elif cmd=='SETCUSTOMITEMTEXTCOLOR': item['color']=self.value(args[1])
                elif cmd=='SETCUSTOMITEMVALUE': item['rows'].pop(int(args[1]),None)
                elif cmd=='SETCUSTOMITEMABIL': item['abil'][(int(args[1]),int(args[2]))]=self.value(args[3])
                elif cmd=='SETCUSTOMITEMVALUEEX': item['rows'][int(args[1])]=(self.value(args[3]),self.value(args[4]),self.value(args[5]))
                elif cmd=='SETNEWITEMVALUE':
                    item['native'][int(args[1])]=(item['native'].get(int(args[1]),0) if args[2]=='+' else 0)+self.value(args[3])
                elif cmd=='CHANGEITEMUPGRADECOUNT': item['stars']=self.value(args[2])
                elif cmd=='UPDATEITEM': self.events.append((self.time,'snapshot',box,deepcopy(item)))
                elif cmd=='RETURNBOXITEM': item['returned']=True
                else: raise AssertionError(cmd)
            elif cmd in ('SETUPGRADEITEM','SENDMSG','MESSAGEBOX','CLOSE','UNALLOWITEMINTOBOX','OPENMERCHANTBIGDLG'): pass
            else: raise AssertionError(('unsupported action',name,label,line))

    def drain(self):
        while self.queue:
            self.time,_,name,label=heapq.heappop(self.queue)
            self.execute(name,label)


def random_path(category=0, quality='普通', breakthrough=False, tier=0):
    def choose(name,label,cmd,args):
        if cmd=='RANDOM': return int(args[0])=={'神佑':350,'天赐':300,'圣级':250,'仙级':150,'灵级':3,'上古':5,'传说':10}.get(quality,-1)
        a,b=map(int,args)
        if b==1000: return breakthrough
        if a==1 and b<=15: return b==15-category
        if (a,b)==(80,100): return tier==0
        if (a,b)==(40,100): return tier==0
        if (a,b)==(40,60): return tier==1
        raise AssertionError(('unexpected RNG',cmd,args))
    return choose
