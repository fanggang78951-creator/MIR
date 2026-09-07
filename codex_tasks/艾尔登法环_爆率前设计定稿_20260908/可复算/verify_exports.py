"""Independent XLSX read-back verification. Standard-library ZIP/XML; no workbook edits."""
from pathlib import Path
import json, math, zipfile, xml.etree.ElementTree as ET, hashlib
B=Path(__file__).resolve().parent;OUT=B.parent
R=json.loads((B/'results/design_final.json').read_text())
S=json.loads((B/'inputs/snapshot_all.json').read_text())
NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
EXPECTED=json.loads((OUT/'核验/公式对照期望.json').read_text())
checks=[]
def ck(label,ok,detail=''):
 checks.append({'check':label,'pass':bool(ok),'detail':detail})
def col(n):
 s=''
 while n:n,k=divmod(n-1,26);s=chr(65+k)+s
 return s
def same(x,y):
 if x in ('',None) and y in ('',None):return True
 if isinstance(x,(int,float)) and isinstance(y,(int,float)):return math.isclose(x,y,rel_tol=1e-11,abs_tol=1e-8)
 return x==y
cache={};stats=[]
for file in sorted(OUT.glob('*.xlsx')):
 with zipfile.ZipFile(file) as z:
  ck('XLSX ZIP完整',z.testzip() is None,file.name)
  strings=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   strings=[''.join(e.itertext()) for e in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si',NS)]
  rels={e.get('Id'):e.get('Target') for e in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
  sheets={};formula_count=0;error_cells=[]
  for sh in ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',NS):
   target=rels[sh.get('{'+REL+'}id')]
   target=target.lstrip('/') if target.startswith('/') else 'xl/'+target
   root=ET.fromstring(z.read(target));cells={}
   for c in root.findall('.//m:sheetData/m:row/m:c',NS):
    addr=c.get('r');typ=c.get('t');v=c.find('m:v',NS);val=v.text if v is not None else None
    if typ=='e':error_cells.append((sh.get('name'),addr,val))
    if typ=='s':val=strings[int(val)] if val is not None else None
    elif typ=='inlineStr':val=''.join(c.find('m:is',NS).itertext())
    elif typ=='b':val=val=='1'
    elif typ not in ('str','e') and val is not None:
     number=float(val);val=int(number) if number.is_integer() else number
    cells[addr]=val
    if c.find('m:f',NS) is not None:formula_count+=1
   sheets[sh.get('name')]=cells
  ck('错误单元格为零',not error_cells,repr(error_cells[:10]))
  stats.append({'file':file.name,'sheets':len(sheets),'formula_cells':formula_count,'error_cells':len(error_cells),'bytes':file.stat().st_size})
  cache[file.name]=sheets
for a in EXPECTED:
 got=cache[a['file']][a['sheet']].get(a['cell'])
 ck('公式缓存与独立计算一致',same(got,a['expected']),f"{a['file']}:{a['sheet']}!{a['cell']} expected={a['expected']} got={got}")
gear=cache['01_817装备定稿总表_V3.0.xlsx']['装备导入表']
heads=list(next(iter(R['gear'].values())))
for row,item in enumerate(R['gear'].values(),2):
 for c,k in enumerate(heads,1):ck('817装备逐格回读',same(gear.get(f'{col(c)}{row}'),item.get(k)),item['名称']+':'+k)
fate=cache['05_100命格_属性冻结规则统一_V2.2.xlsx']
for name in ('命格定义','命格属性','颜色方案','数据字典'):
 rows=[list(r) for r in S['fate'][name] if r and any(v is not None for v in r)]
 for row,values in enumerate(rows,1):
  for c,value in enumerate(values,1):ck('命格原属性与ID冻结',same(fate[name].get(f'{col(c)}{row}'),value),f'{name}:{row}:{c}')
mon=cache['02_561怪与地图人物_设计定稿_V1.0.xlsx']['怪物导入表']
for row,m in enumerate(R['monsters'],2):
 values=[m['name'],m.get('Appr'),m['Lvl'],m['Exp'],m['HP'],0,m['AC'],m['MAC'],m['DC'],m['DCMAX'],None,None]
 for c,value in enumerate(values,1):ck('561怪导入格回读',same(mon.get(f'{col(c)}{row}'),value),m['id']+':'+str(c))
growth=cache['03_NPC任务与永久成长_设计定稿_V1.0.xlsx']
collection=json.loads((B/'inputs/combat.json').read_text())['collection_rows']
ck('图鉴导出619条',sum(k.startswith('A') and k[1:].isdigit() and int(k[1:])>=5 and bool(v) for k,v in growth['单件图鉴'].items())==619)
for row,r in enumerate(collection,5):
 for c,value in enumerate(r,1):ck('图鉴619逐格回读',same(growth['单件图鉴'].get(f'{col(c)}{row}'),value),r[2]+':'+str(c))
for row in range(5,51):
 cid=growth['地图整页46组'].get(f'A{row}');group=growth['地图整页46组'].get(f'B{row}')
 expected=sum(r[0]==cid and r[1]==group for r in collection)
 ck('46整页数量与619匹配',growth['地图整页46组'].get(f'C{row}')==expected,str((cid,group)))
for row in range(5,15):
 cid=growth['大陆全收集'].get(f'A{row}')
 ck('10大陆数量与619匹配',growth['大陆全收集'].get(f'C{row}')==sum(r[0]==cid for r in collection),str(cid))
drop=cache['04_掉落内容与回收_爆率空置_V1.0.xlsx']['掉落候选内容']
for i in range(5,5405):ck('概率导出保持空置',drop.get(f'H{i}') is None,str(i))
failed=[x for x in checks if not x['pass']]
report={'passed':len(checks)-len(failed),'failed':len(failed),'formula_cross_checks':len(EXPECTED),'equipment_cells':817*69,'monster_cells':561*12,'fate_cells_checked':sum(x['check']=='命格原属性与ID冻结' for x in checks),'atlas_cells_checked':619*15,'workbooks':stats,'failures':failed[:50],'scope':'数据、文件结构和近似模型输入一致性；不是游戏内胜率测试'}
(OUT/'核验/最终导出核验.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
if failed:raise SystemExit(1)
