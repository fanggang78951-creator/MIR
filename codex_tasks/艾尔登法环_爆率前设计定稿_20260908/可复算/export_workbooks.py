"""Workbook views of sealed data. Uses artifact_tool only, never edits the server."""
from pathlib import Path
from collections import defaultdict
import json,math,copy,re
from artifact_tool import Workbook,SpreadsheetFile
B=Path(__file__).resolve().parent;OUT=B.parent
R=json.loads((B/'results/design_final.json').read_text());N=json.loads((B/'inputs/normalized_current.json').read_text());S=json.loads((B/'inputs/snapshot_all.json').read_text());O=json.loads((B/'inputs/source_inputs.json').read_text())
P={p['id']:p for p in R['profiles']};M={m['id']:m for m in R['monsters']}
MAN=[];EX=[];BUILT={}
NAVY='#17365D';BLUE='#245B83';PALE='#EAF1F7';GRAY='#536274';TEAL='#107C78'
def col(i):
 s=''
 while i:
  i,a=divmod(i-1,26);s=chr(65+a)+s
 return s
def txt(x):
 if x is None:return ''
 if isinstance(x,(list,tuple)):return '；'.join(map(str,x))
 if isinstance(x,dict):return '；'.join(f'{k}×{int(v) if isinstance(v,(float,int)) and float(v).is_integer() else v}' for k,v in x.items())
 return str(x)
def book():return Workbook.create()
def sheet(w,name,heads,rows,note='',widths=None,raw=False):
 sh=w.worksheets.add(name);nc=len(heads);hr=1 if raw else 4;end=hr+len(rows)
 if not raw:
  sh.merge_cells(f'A1:{col(nc)}1');sh.get_range('A1').values=[[name+'｜爆率前设计定稿']]
  sh.get_range(f'A1:{col(nc)}1').format={'fill':NAVY,'font':{'bold':True,'color':'#FFFFFF','size':14},'row_height':28}
  sh.merge_cells(f'A2:{col(nc)}3');sh.get_range('A2').values=[[note]]
  sh.get_range(f'A2:{col(nc)}3').format={'fill':PALE,'font':{'color':GRAY,'size':10},'wrap_text':True,'vertical_alignment':'center','row_height':24}
 data=[heads]+rows
 for r in data:
  if len(r)!=nc:raise ValueError((name,len(r),nc,r))
 if data:sh.get_range(f'A{hr}:{col(nc)}{end}').values=data
 sh.get_range(f'A{hr}:{col(nc)}{end}').format={'font':{'size':10},'row_height':22,'vertical_alignment':'center','wrap_text':True}
 sh.get_range(f'A{hr}:{col(nc)}{hr}').format={'fill':BLUE,'font':{'bold':True,'color':'#FFFFFF','size':10},'row_height':36,'wrap_text':True,'vertical_alignment':'center'}
 for i in range(nc):
  width=(widths[i] if widths and i<len(widths) else 16)
  if heads[i]=='备注':width=42
  if heads[i]=='悬浮分类':width=14
  sh.get_range(f'{col(i+1)}1:{col(i+1)}{end}').format.column_width=min(42,width)
 for ri,row in enumerate(rows,hr+1):
  longest=max((len(str(v)) for v in row if isinstance(v,str)),default=0)
  if longest>90:sh.get_range(f'A{ri}:{col(nc)}{ri}').format.row_height=78
  elif longest>45:sh.get_range(f'A{ri}:{col(nc)}{ri}').format.row_height=48
 sh.freeze_panes.freeze_rows(hr)
 if len(rows) and nc<25:
  try:sh.tables.add(f'A{hr}:{col(nc)}{end}',True,'T'+str(len(w.worksheets.items))+'_'+str(abs(hash(name))%100000))
  except Exception:pass  # filter cosmetics only; core table remains fully populated
 return sh,hr+1,end
def fm(sh,address,matrix):sh.get_range(address).formulas=matrix
def expect(wfile,sh,cell,value):EX.append({'file':wfile,'sheet':sh,'cell':cell,'expected':value})
def keepblock(w,name,block,note='',select=None):
 h=next((i for i,r in enumerate(block) if i>=2 and r and r[0] is not None),0)
 # Passed legacy sheets have header at index3 except explicit raw datasets.
 if len(block)>3 and block[3] and block[3][0] is not None:h=3
 head=block[h];rows=[list(x) for x in block[h+1:] if x and any(y is not None for y in x)]
 return sheet(w,name,list(head),rows,note=note)
def finish_layout(w):
 for line in w.inspect({'kind':'sheet','include':'id,name'}).ndjson.splitlines():
  item=json.loads(line)
  if item.get('kind')!='sheet':continue
  sh=w.worksheets.get_item(item['name'])
  addr=item.get('range',item.get('address','A1:A1'))
  m=re.search(r':([A-Z]+)([0-9]+)$',addr)
  if not m:continue
  lastcol,lastrow=m.group(1),int(m.group(2))
  raw=item['name'] in {'装备导入表','怪物导入表','命格定义','命格属性','颜色方案','数据字典'}
  hr=1 if raw else 4
  if lastrow<=hr:continue
  values=w.inspect({'kind':'table','range':f"'{item['name']}'!A{hr}:{lastcol}{hr}",'include':'values','table_max_rows':1,'table_max_cols':100}).ndjson
  heads=json.loads(values).get('values',[[]])[0]
  for j,h in enumerate(heads,1):
   if not isinstance(h,str):continue
   fmt=None
   if h in {'本大陆准备度','准备度'}:fmt='0.0"%"'
   elif h in {'有效吸收','基础残值比例','输出提升','耐久提升'}:fmt='0.0%'
   elif any(k in h for k in ['秒数','击杀秒','生存预算秒','校准秒数','TTK','每秒刀数','刀每秒','倍率','人物爆率倍数']):fmt='0.00'
   elif any(k in h for k in ['HP','金币','元宝','输出','单击','HPS','回复预算','固定回血']) or h in {'Exp','DC','DCMAX','AC','MAC','攻击上限','攻击下限','防御','魔御'}:fmt='#,##0'
   if fmt:sh.get_range(f'{col(j)}{hr+1}:{col(j)}{lastrow}').format.number_format=fmt
  if item['name']=='现行规则':sh.get_range(f'A5:B{lastrow}').format.row_height=56
 return w

def export(w,filename,preview_sheet=None,preview_range='A1:H14'):
 BUILT[filename]=w
 finish_layout(w)
 errs=w.inspect({'kind':'match','search_term':'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A','options':{'use_regex':True,'max_results':100}}).ndjson
 if 'matched 0 entries' not in errs:raise RuntimeError(filename+' '+errs)
 if preview_sheet:
  w.render({'sheet_name':preview_sheet,'range':preview_range,'scale':1.3}).save(str(OUT/'核验'/ (filename.replace('.xlsx','.png'))))
 path=OUT/filename;SpreadsheetFile.export_xlsx(w).save(str(path));MAN.append({'file':filename,'formula_scan':errs,'bytes':path.stat().st_size})
 print(filename,path.stat().st_size)
 return path

def equipment():
 w=book();fn='01_817装备定稿总表_V3.0.xlsx'
 heads=list(next(iter(R['gear'].values())).keys());rows=[[g.get(k) for k in heads] for g in R['gear'].values()]
 sheet(w,'装备导入表',heads,rows,raw=True,widths=[25,14,12]+[12]*(len(heads)-3))
 sums=[['冻结', 'C1/C2及前期合成',265,'属性不改；名称、部位、资源号全部保留'],['调整','C3-C10普通专属',227,'原有普通战斗字段；不新增处决、突破或最大爆率'],['联动','稀有/BOSS/合成',93,'维护同阶段稀有及合成价值；不是额外新增装备'],['覆盖','全装备',817,'561怪的619件定向专属+160制式+38合成'],['边界','爆率',None,'本批不填物品触发概率；不宣称游戏内已经验证']]
 sheet(w,'定稿摘要',['处理','对象','件数','说明'],sums,'本版替代旧装备数值结论；逐字段变动见变更清单。',[12,28,12,42])
 changes=[[x[k] for k in ['name','c','group','role','part','field','old','new','reason']] for x in R['equipment_changes']]
 sheet(w,'变更清单',['装备','大陆','地图组','来源级别','部位','字段','旧值','新值','原因'],changes,'只修改清单内字段；新文件整表用于读取，服务器更新应按名称和字段白名单执行。',[25,8,20,14,12,16,18,18,40])
 rr=[]
 for a in R['ordinary_ladder']:
  rr.append([a['c'],a['gi']+1,a['group'],len(a['pool']),len(a['selected']),txt(a['selected']),a['entry_dps'],a['after_dps'],None,a['entry_ehp'],a['after_ehp'],None,a['note']])
 sh,st,en=sheet(w,'普通50至70换装',['大陆','组序','地图组','普通池种数','取得种数','选择实物','换装前输出','换装后输出','输出提升','换装前等效HP','换装后等效HP','耐久提升','口径'],rr,'仅普通装备分支对照，不夹带图鉴/称号奖励；BOSS与必做合成属于另一条可提前推进的路线。',[8,8,19,10,10,40,16,16,12,17,17,12,42])
 fm(sh,f'I{st}:I{en}',[[f'=H{i}/G{i}-1'] for i in range(st,en+1)]);fm(sh,f'L{st}:L{en}',[[f'=K{i}/J{i}-1'] for i in range(st,en+1)])
 sh.get_range(f'I{st}:I{en}').format.number_format='0.0%';sh.get_range(f'L{st}:L{en}').format.number_format='0.0%'
 for i,a in enumerate(R['ordinary_ladder'],st):expect(fn,sh.name,f'I{i}',a['offense']-1);expect(fn,sh.name,f'L{i}',a['survival']-1)
 cr=[]
 for x in R['crafted_comparisons']:
  cr.append([x['name'],x['c'],x['part'],x['reference_name'],x['reference_type'],x['empty'],x['boss'],x['crafted'],None,None,x['attack_ratio']])
 sh,st,en=sheet(w,'合成边际收益',['合成件','大陆','部位','比较对象','对象性质','空槽输出','BOSS件输出','合成件输出','单件边际倍率','整人倍率','基础攻击倍率'],cr,'只比较常规单刀增量；2-3倍是单件贡献，不是整个人物DPS翻倍。明确的合成标尺不是新物品。',[25,8,14,32,40,18,18,18,15,13,16])
 fm(sh,f'I{st}:I{en}',[[f'=(H{i}-F{i})/(G{i}-F{i})'] for i in range(st,en+1)]);fm(sh,f'J{st}:J{en}',[[f'=H{i}/G{i}'] for i in range(st,en+1)])
 sh.get_range(f'I{st}:K{en}').format.number_format='0.00'
 for i,x in enumerate(R['crafted_comparisons'],st):expect(fn,sh.name,f'I{i}',x['marginal_ratio']);expect(fn,sh.name,f'J{i}',x['whole_ratio'])
 ident=[]
 for n,g in R['gear'].items():
  mm=R['equipment_meta'][n];ids=N['item_sources'].get(n,[])
  ident.append([n,mm['c'],mm['role'],g['部位'],g['来源编号'],txt(ids),n in N['crafts']])
 sheet(w,'身份与来源',['装备','大陆','来源分类','部位','外观来源编号','怪物/制作来源','合成成品'],ident,'来源编号是外观/模板引用，不是StdItems唯一Idx；复用外观时每件装备仍须独立物品记录。',[25,9,15,15,16,42,12])
 return export(w,fn,'定稿摘要','A1:D11')

def combat():
 w=book();fn='02_561怪与地图人物_设计定稿_V1.0.xlsx'
 gg=[x for x in R['gate_checks'] if x['case']=='p70']
 overview=[[x['c'],x['gate'],x['HP'],x['ttk'],x['completion'],P[x['profile']]['raw']['韧性'],x['toughness_gap'],'预算可过' if x['win'] else '失败'] for x in gg]
 sheet(w,'十大陆守关总览',['大陆','守关BOSS','HP','参考击杀秒数','本大陆准备度','人物韧性','有效韧性','粗算结论'],overview,'约70%是平衡样本，不是传送条件。唯一跨大陆硬条件仍为击杀守关。低25韧性只改变韧性，不额外增加眩晕。',[9,31,21,17,17,14,15,15])
 mh=['Name','Appr','Lvl','Exp','HP','MP','AC','MAC','DC','DCMAX','HIT','SPEED']
 data=[[m['name'],m.get('Appr'),m['Lvl'],m['Exp'],m['HP'],0,m['AC'],m['MAC'],m['DC'],m['DCMAX'],None,None] for m in R['monsters']]
 sheet(w,'怪物导入表',mh,data,raw=True,widths=[28,10,10,16,23,8,16,16,16,16,9,9])
 detail=[[m['id'],m['c'],m['group'],m['role'],m['name'],m['HP'],m['DC'],m['DCMAX'],m['AC'],m['MAC'],m['attack_interval_ms'],m['reference'],m['design_dps'],None,txt(m['maps']),m['runtime_numeric_range']] for m in R['monsters']]
 sh,st,en=sheet(w,'怪物设计与接口',['逻辑ID','大陆','地图组','分类','怪名','HP','攻击下限','攻击上限','防御','魔御','攻击间隔毫秒','参考人物ID','校准输出','校准秒数','地图键','数字容量'],detail,'SPEED未映射时留空并保留现服；攻击间隔毫秒单独对接，不直接写成SPEED。Appr空白表示不修改模型。',[24,8,20,14,26,23,16,16,15,15,17,14,21,14,42,23])
 fm(sh,f'N{st}:N{en}',[[f'=F{i}/M{i}'] for i in range(st,en+1)])
 for i,m in enumerate(R['monsters'],st):expect(fn,sh.name,f'N{i}',m['HP']/m['design_dps'])
 maps=[[x['map_key'],x.get('runtime_id'),x['c'],x['group'],x['韧性要求'],x['处决要求'],txt(x['residents']),'真实地图号继承现服，不新建地图' if not x.get('runtime_id') else '按既有地图号更新'] for x in R['maps']]
 sheet(w,'地图韧性与处决',['地图键','正式地图号','大陆','地图组','韧性要求','处决要求百分点','住民怪物ID','对接说明'],maps,'171图各一套要求；同图的普通、地图BOSS和守关读取相同值。C1现有层名匹配，禁止编造地图编号。',[32,16,8,20,13,17,42,38])
 pl=[[e['monster'],M[e['monster']]['name'],e['map'],e['role'],e['reference'],e['ttk'],e['toughness_gap'],e['ordinary_single_hit'],e['highest_single_hit'],'预算可生存' if e['approx_win'] else '压力情景'] for e in R['encounters']]
 sheet(w,'逐落点对应',['怪物ID','怪名','地图键','分类','参考人物','预计击杀秒数','韧性差','普通最高单击','处决最高单击','粗算结果'],pl,'622条怪物—地图落点；不更改刷新密度，不把数量当成确定击杀量。',[24,28,32,14,14,17,12,21,21,18])
 rawheads=['人物ID','大陆','组序','状态']+list(R['profiles'][0]['raw'])
 rawrows=[[p['id'],p['c'],p['gi']+1,p['label']]+[p['raw'][k] for k in rawheads[4:]] for p in R['profiles']]
 sheet(w,'人物全来源合计',rawheads,rawrows,'原始来源同类加算；每项来源引用和实物记录在可复算/results/design_final.json。',[12,8,8,34]+[15]*(len(rawheads)-4))
 pp=[]
 for p in R['profiles']:
  d=p['derived'];pp.append([p['id'],p['c'],p['label'],p['parent'],d['面板攻击上限'],d['HP'],d['有效吸收'],d['有效攻速点'],d['刀每秒'],d['纯属性DPS'],2,None,d['吸血理论上限每秒'],1.3,None,p['raw']['每秒回血'],None,p['neck'],txt(p['fates']),d['有效爆率_主换算']])
 sh,st,en=sheet(w,'人物战斗面板',['人物ID','大陆','状态','上一步','攻击上限','HP','有效吸收','有效攻速点','每秒刀数','纯属性输出','技能效率','含技能输出','普攻可吸血HPS','吸血效率','含技能吸血','固定回血','总回复预算','人物幸运','命格ID','人物爆率倍数'],pp,'技能统一x2，吸血最多x1.3。只作大体战斗预算，不将技能伤害、固定切割或过杀反复计入吸血。',[12,8,34,12,18,21,14,14,14,20,12,22,20,12,20,16,20,14,38,17])
 for target,fs in [('L',[f'=J{i}*K{i}' for i in range(st,en+1)]),('O',[f'=M{i}*N{i}' for i in range(st,en+1)]),('Q',[f'=O{i}+P{i}' for i in range(st,en+1)])]:fm(sh,f'{target}{st}:{target}{en}',[[f] for f in fs])
 for i,p in enumerate(R['profiles'],st):
  d=p['derived'];expect(fn,sh.name,f'L{i}',d['技能效率DPS']);expect(fn,sh.name,f'O{i}',d['吸血HPS']);expect(fn,sh.name,f'Q{i}',d['总回复HPS'])
 gates=[[x['c'],x['gate'],x['case'],x['profile'],x['completion'],x['toughness_gap'],x['ttk'],x['survival_seconds'],x['peak_hit_to_player'],x['player_hp'],'可过' if x['win'] else '生存不足'] for x in R['gate_checks']]
 sheet(w,'守关准备与韧性对照',['大陆','守关','情景','人物ID','准备度','韧性差','预计击杀秒','生存预算秒','最高单击','人物HP','预算结论'],gates,'不是随机胜率模拟；生存预算空值表示平均回复可覆盖，不意味着不会因引怪或操作死亡。',[8,28,22,13,12,12,16,17,20,20,16])
 gr=[]
 for g in R['groups']:
  gr.append([g['c'],g['gi']+1,g['group'],g['entry'],g['ordinary'],g['本组入场普通TTK'],g['裸跳下一组TTK'],g['普通60后下一组TTK'],txt(g.get('strong_items',[])),g.get('design_decision','末组按约70%准备度守关')])
 sheet(w,'强装主线与接棒',['大陆','组序','地图组','入场人物','普通换装人物','本组TTK','裸跳下一组TTK','换装后下一组TTK','已持BOSS或合成件','处理结论'],gr,'强装主线允许提前推进，不把无BOSS/合成的普通专项路线混成同一人物；不再使用20%硬门槛。',[8,8,21,14,16,13,17,18,42,42])
 return export(w,fn,'十大陆守关总览','A1:H14')

def growth():
 w=book();fn='03_NPC任务与永久成长_设计定稿_V1.0.xlsx'
 recrows=[]
 for a in N['recipes']:
  external=a['type'] in ('既有成长','命格商店','命格槽位') or a['c']==0
  coststatus='继承现有入口；0不是免费' if external else '本表确定值；灵符替代路径沿用既有实现'
  recrows.append([a['id'],a['c'],a['npc_location_c'],a['npc'],a['type'],a['output'],txt(a['bases']),txt(a['materials']),a['gold'],a['yuan'],a['budget_count'],None,None,a['mandatory'],coststatus])
 sh,st,en=sheet(w,'127配方与操作',['记录ID','成长大陆','NPC所在大陆','NPC','类别','产物或操作','独立基础件','单次材料','单次金币','单次元宝','预算次数','阶段金币','阶段元宝','必做制作','继承范围'],recrows,'C2是长期系统主城：地点不等于完成大陆。数量乘次从明细计算，不再二次x100。',[24,10,13,26,16,32,42,42,21,19,12,23,21,12,42])
 fm(sh,f'L{st}:L{en}',[[f'=I{i}*K{i}'] for i in range(st,en+1)]);fm(sh,f'M{st}:M{en}',[[f'=J{i}*K{i}'] for i in range(st,en+1)])
 for i,a in enumerate(N['recipes'],st):expect(fn,sh.name,f'L{i}',a['gold']*a['budget_count']);expect(fn,sh.name,f'M{i}',a['yuan']*a['budget_count'])
 ar=[]
 for n,a in N['crafts'].items():
  g=R['gear'][n];ar.append([a['id'],n,a['c'],g['部位'],txt({k:g[k] for k in list(g)[3:67] if g[k] not in (None,'',0)}),a['success'],'按唯一成品物品属性；替换旧级，不重复叠历史级'])
 sheet(w,'制作成品属性对接',['记录ID','成品','成长大陆','部位','本次成品属性','成功规则','叠加与替换'],ar,'38成品读取装备定稿总表；没有把旧装备摘要重新拷贝到NPC。',[24,28,11,15,42,35,38])
 deps=[[a['recipe'],a['c'],a['output'],a['field'],a['name'],a['qty'],txt(a['sources']),txt(a['source_roles']),a['accessible_preclear']] for a in N['dependency_audit']]
 sheet(w,'345项首杀前依赖',['记录ID','大陆','产物','字段','所需物品','数量','来源ID','来源分类','首杀前可达'],deps,'地图BOSS与守关分开；地图BOSS来源能在本次守关首杀前取得。不是爆率或获取时长保证。',[24,8,28,12,26,12,42,26,14])
 qr=[[a['id'],a['c'],a['group'],a['name'],txt(a['materials']),txt(a['stats']),a['postclear'],'任务允许后补，不新增传送门槛'] for a in N['quests']]
 sheet(w,'8项既有大陆任务',['任务ID','大陆','地图组','任务','材料','奖励','守关后任务','规则'],qr,'C3以后不新增魂魄任务链。收集图鉴、NPC制作和贯穿称号仍继续承担成长。',[24,8,21,30,42,42,15,38])
 for target,legacy in [('贯穿称号10阶段','01_贯穿称号'),('独立称号6项','02_独立称号'),('转生20转','03_二十转奖励'),('群攻生肖5级','05_群攻生肖'),('单件图鉴','07_专属单件图鉴'),('地图整页46组','08_地图整页图鉴'),('大陆全收集','09_大陆全收集'),('大陆材料图鉴','10_大陆材料图鉴')]:
  block=copy.deepcopy(S['npc'][legacy])
  # All 619 entries, not the earlier 563-row atlas. Reward values are unchanged.
  collection=json.loads((B/'inputs/combat.json').read_text())['collection_rows']
  if legacy=='07_专属单件图鉴':block=block[:4]+copy.deepcopy(collection)
  elif legacy=='08_地图整页图鉴':
   for row in block[4:]:
    if row and row[0]:row[2]=sum(x[0]==row[0] and x[1]==row[1] for x in collection)
  elif legacy=='09_大陆全收集':
   for row in block[4:]:
    if row and row[0]:row[2]=sum(x[0]==row[0] for x in collection)
  keepblock(w,target,block,'继承已确认奖励，619件登记范围和整页数量同步；人物永久奖励一次生效，阶段升级按覆盖/增量规则处理。')
 keepblock(w,'神印255档',copy.deepcopy(S['econ']['10_神印255档']),'神印为全游戏长期成长，C2不要求255档。费用继承大数值版明细，材料为野兽骨片。')
 wash=[a for a in N['recipes'] if a['type'] in ('普通洗练','开光','项链幸运')]
 sheet(w,'洗练幸运消耗接口',['操作ID','计费档','操作','失色及其他材料','单次金币','单次元宝','绑定规则'],[[a['id'],a['c'],a['type'],txt(a['materials']),a['gold'],a['yuan'],'人物幸运永久、最高8；更换项链不清零' if a['type']=='项链幸运' else '洗练绑定装备实例；按物品自身档计费；不能跨地图低价洗'] for a in wash],'洗练固定材质失色锻造石；普通洗练词条数1-8；7/8条才可开光，不默认前期全身8条。',[24,10,16,36,20,20,42])
 pool=O['wash_pool'];sheet(w,'洗练属性与权重',list(pool[0]),[list(a) for a in pool[1:]],'按已确认属性池；无效候选过滤后重新归一化，不新增命格或装备内部ID。')
 bonus=[['西境拓荒者',1,1],['满月见证者',1,2],['永霜朝圣者',1,0],['黄金律见证者',1,0],['艾尔登之王',1,0]]
 sheet(w,'独立称号配套增量',['已有称号','攻速突破增量','吸收上限增量'],bonus,'这5项为既有装备重规划配套增量，前面的基础表不包含这些列。实现时各称号只加一次。',[30,22,22])
 sheet(w,'圣律圣物最终口径',['阶段','两条成长线','攻魔道每件','功能与费用'],[['C1满级','圣律之剑／黄金圣物',50,'C1完全不改；切割5000/固定回血2000继续原样'],*[[f'C2 LV{i}','圣律真言／黄金之心',v,f'原鞭尸/首刀{i}%，传送/复活和既有费用不改'] for i,v in enumerate([60,75,95,120,145,170,200,230,255,280],1)]],'只削C2基础值。它们不与C1旧形态同时叠加。',[15,29,19,42])
 return export(w,fn,'圣律圣物最终口径','A1:D15')

def drops():
 w=book();fn='04_掉落内容与回收_爆率空置_V1.0.xlsx'
 pools={'自身专属':'每件本体专属独立判定；不复制整池触发次数','本图普通兼掉候选':'本图兼掉池候选；每次触发选一件，等权起步','材料独立候选':'每种材料独立判定；数量为触发后的叠加数','六神器公共池':'先判定公共池，再按既有六神器池选一件','制式独立候选':'每次触发从本组套序候选选一件'}
 rows=[[a['monster'],M[a['monster']]['name'],a['c'],M[a['monster']]['role'],a['pool'],a['item'],a['quantity'],None,pools[a['pool']]] for a in R['drop_content']]
 sheet(w,'掉落候选内容',['怪物ID','怪名','大陆','分类','候选池','物品或池引用','单次数量','基础触发概率','抽取结构'],rows,'5400条是内容/候选关系，不是5400次独立判定。全部基础触发概率留空；不将空概率写成0或1。',[25,28,8,14,24,34,13,17,42])
 rec={x[6]:x[8] for x in S['econ']['07_专属分解明细'][4:] if x[0]}
 rec.update({x[0]:x[7] for x in S['new56']['来源与回收候选'][4:] if x[0]})
 sr=[]
 for m in R['monsters']:
  for n in m['items']:
   sr.append([n,m['c'],m['group'],m['role'],m['id'],rec[n],'否','手动确认，不默认勾选'])
 sheet(w,'619专属分解',['装备','大陆','地图组','来源分类','怪物ID','固定失色数量','受回收加成','操作方式'],sr,'失色只来自既有专属拆解，数量沿用已放大版本，不再次x10；货币50%加成不作用于材料。',[28,8,20,15,27,16,14,26])
 mp=[]
 for a in N['material_prices']:mp.append([a['名称'],a['大陆ID'],a['类别'],a['基础金币'],a['基础元宝'],1.5,None,None,a['回收方式'],a['计入货币产出模型'],a['主要用途']])
 sh,st,en=sheet(w,'81材料回收',['材料','大陆','类别','基础金币','基础元宝','货币回收倍率','加成金币','加成元宝','方式','计入基准产出','用途'],mp,'只有金币/元宝回收按总50%增益。核心稀缺材料先供成长，不把全部掉落都当可回收余额。',[27,12,21,20,20,15,20,20,25,16,42])
 fm(sh,f'G{st}:G{en}',[[f'=D{i}*F{i}'] for i in range(st,en+1)]);fm(sh,f'H{st}:H{en}',[[f'=E{i}*F{i}'] for i in range(st,en+1)])
 for i,a in enumerate(N['material_prices'],st):expect(fn,sh.name,f'G{i}',a['基础金币']*1.5);expect(fn,sh.name,f'H{i}',a['基础元宝']*1.5)
 keepblock(w,'20套制式回收',copy.deepcopy(S['econ']['06_制式装备回收']),'每套8种物品共享本行单件价格，不是整套总额；物品爆率最后统一反算。')
 cr=[]
 for n,a in N['crafts'].items():cr.append([n,a['c'],a['gold'],a['yuan'],.2,1.5,None,None,'不返基础件/材料；不计基准货币供给'])
 sh,st,en=sheet(w,'38合成残值',['成品','大陆','合成金币','合成元宝','基础残值比例','货币回收倍率','实返金币','实返元宝','限制'],cr,'以实际制作货币成本为基数。基础残值20%，满回收实际返30%；材料不退。',[27,8,22,20,16,16,22,20,42])
 fm(sh,f'G{st}:G{en}',[[f'=C{i}*E{i}*F{i}'] for i in range(st,en+1)]);fm(sh,f'H{st}:H{en}',[[f'=D{i}*E{i}*F{i}'] for i in range(st,en+1)])
 for i,(n,a) in enumerate(N['crafts'].items(),st):expect(fn,sh.name,f'G{i}',a['gold']*.3);expect(fn,sh.name,f'H{i}',a['yuan']*.3)
 keepblock(w,'高价值手动回收',copy.deepcopy(S['econ']['08_高价值回收']),'追梦、称号物、任务物保留低频手动回收，不加入正常产出速度模型。六神器真实属性不在本批覆盖。')
 mr=[]
 for name,ids in N['material_sources'].items():
  uses=[a['id'] for a in N['recipes'] if name in a['materials']]+[a['id'] for a in N['quests'] if name in a['materials']]
  mr.append([name,txt(ids),txt(uses),'成长或图鉴/回收用途；不得按名称推定守关独占'])
 sheet(w,'材料来源与用途',['材料','来源怪物/系统ID','已知消耗记录','使用规则'],mr,'C2长期系统材料有跨大陆来源。守关Q04身份不改；本轮配方已改用地图BOSS来源。',[28,42,42,42])
 return export(w,fn,'619专属分解','A1:H12')

def fate():
 w=book();fn='05_100命格_属性冻结规则统一_V2.2.xlsx'
 # Exact name/ID/quality/attribute cells from approvedV2.1; documentation only supersedes stale duplicate language.
 for name in ('命格定义','命格属性','颜色方案','数据字典'):
  block=[list(r) for r in S['fate'][name] if r and any(v is not None for v in r)]
  sheet(w,name,block[0],block[1:],raw=True,widths=[14,14,25,18,30,20,25,42])
 rules=[['同名命格','不可同时装备；不是仅标准人物不重复。压力人物同样禁止重复'],['初期槽位','首次开放2槽，第一大陆中段3槽；之后随已有主线开至8槽'],['颜色','绿/黄/橙/红/彩各20；全充值只在已开放槽位追求全彩'],['红色攻速','风驰电掣：攻击速度3、攻速突破1'],['彩色攻速','快人三步：攻击速度3、攻速突破5；突破不等于直接获得5普通攻速'],['数据边界','本版不改100个命格任何名称、ID、数值与颜色。只统一执行规则'],['路由','攻速突破接入已有真实绑定；不编造内部ID；预检拒绝未知属性'],['既有抽取','仍沿用现有品质保底与付费入口；不新增同名多槽叠加']]
 sheet(w,'现行规则',['项目','必须执行的口径'],rules,'用户已确认同名不能重复。旧V2.1文件中允许重复作压力情景的文字在本版废止。',[22,42])
 return export(w,fn,'现行规则','A1:B12')

def save_logs():
 (OUT/'核验'/'工作簿导出.json').write_text(json.dumps(MAN,ensure_ascii=False,indent=2))
 (OUT/'核验'/'公式对照期望.json').write_text(json.dumps(EX,ensure_ascii=False,separators=(',',':')))


if __name__=='__main__':
 equipment(); combat(); growth(); drops(); fate(); save_logs()
