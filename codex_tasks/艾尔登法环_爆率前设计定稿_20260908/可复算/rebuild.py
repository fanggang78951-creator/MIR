"""Reproduce the frozen-input numerical design locally; no Git/server access."""
from pathlib import Path
import hashlib,json,subprocess,sys,time
B=Path(__file__).resolve().parent
OUTPUT=B/'results/design_final.json'
IMMUTABLE=['normalized.json','snapshot_all.json','source_inputs.json','combat.json','map_registry.json','baseline_results.json','equipment_comparison_original.json']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 before={name:sha(B/'inputs'/name) for name in IMMUTABLE}
 old=sha(OUTPUT) if OUTPUT.exists() else None;steps=[]
 for name in ['finalize_equipment.py','tune_progression.py','align_crafts.py','build.py','seal.py']:
  start=time.monotonic();result=subprocess.run([sys.executable,str(B/name)],cwd=B,capture_output=True,text=True)
  (B/'results'/('rebuild_'+name+'.log')).write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
  steps.append({'step':name,'returncode':result.returncode,'seconds':round(time.monotonic()-start,3)})
  if result.returncode:
   print(result.stdout[-3000:]);print(result.stderr[-3000:]);raise SystemExit(result.returncode)
 after={name:sha(B/'inputs'/name) for name in IMMUTABLE}
 if before!=after:raise RuntimeError('Immutable input changed.')
 now=sha(OUTPUT)
 report={'steps':steps,'immutable_inputs_unchanged':True,'final_sha256':now,'previous_sha256':old,'identical_to_previous':old==now if old else None,'scope':'仅复算数值。工作簿执行export_workbooks.py；不更新GitHub或服务端。'}
 (B.parent/'核验/可重复构建.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=False,indent=2))
 if '--require-identical' in sys.argv and old!=now:raise SystemExit('Output differs; inspect changes.')
if __name__=='__main__':main()
