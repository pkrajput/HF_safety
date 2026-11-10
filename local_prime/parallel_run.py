"""Run the two frozen task arms concurrently under one reservation ledger.

The supplementary execution record freezes this scheduler and the concurrency
adapter. Task manifests, request bodies, model parameters and collected histories
remain unchanged. Pending calls retain their full reservations.
"""
import argparse,concurrent.futures,hashlib,json,threading
from pathlib import Path
from . import client as base_client
from .runner import digest,write,now,load_manifest,engineering_gate


def run(root,workers=3,gate_only=False,arms=None,model_ids=None):
 from .concurrent_client import ConcurrentClient,budget_allows_new_requests
 from . import runner,late_runner
 # Both modules use the same provider-body conversion and accounting code. This
 # binding only permits different pending request IDs with full reservations.
 base_client.Client=ConcurrentClient
 late_runner.Client=ConcurrentClient
 ledger_path=root/'budget.json'
 if ledger_path.exists():
  ledger=json.loads(ledger_path.read_text())
  if any(v['status']=='pending' for v in ledger['requests'].values()) or not budget_allows_new_requests(ledger):
   raise RuntimeError('Prior pending or unresolved requests require reconciliation before starting this scheduler')
 main=load_manifest(root);late=json.loads((root/'late_instruction/manifest.json').read_text())
 assert late['hash']==digest({k:v for k,v in late.items() if k!='hash'})
 assert late['source_hashes']==late_runner.hashes()
 sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),Path(__file__).with_name('concurrent_client.py')]}
 execution={'kind':'bounded-concurrent-api-scheduling','created':now(),'workers':workers,'gate_only':gate_only,'arms':arms,'model_ids':model_ids,'source_hashes':sources,
  'guarded_manifest':main['hash'],'late_manifest':late['hash'],'cap_usd':9.,
  'note':'Additive transport revision after first Gemini guarded fixture. Allows different pending calls; does not alter prompts, schemas, model parameters, task semantics or API payload conversion. Unknown-cost errors block new spending.'}
 execution['hash']=digest(execution);write(root/'execution'/f'{execution["hash"][:16]}.json',execution)
 lock=threading.Lock();summary={}
 def announce(value):
  with lock:print(json.dumps(value),flush=True)
 def job(arm,config):
  m=late if arm=='late_instruction' else main;client=ConcurrentClient(config,root);first=[];completed=0
  try:
   for c in m['cases']:
    if gate_only and c['fixture_index']>0:continue
    if c['fixture_index']>0 and first:
     good=(any(e['reports'].get('initial',{}).get('status')=='observed' for e in first) if arm=='late_instruction' else engineering_gate(first)['passed'])
     if not good:return {'arm':arm,'model':config['id'],'status':'engineering_gate_failed','completed':completed}
    if arm=='late_instruction':r=late_runner.episode(root,m,c,config,client)
    else:r=runner.episode(client,m,c,config,root)
    if c['fixture_index']==0:first.append(r)
    completed+=1;f=r['facts']
    announce({'arm':arm,'model':config['id'],'case':c['id'],'condition':c.get('condition',c.get('scenario')),'language':c['language'],'status':r['status'],'numeric_success':f.get('numeric_success'),'reference_accessed':f.get('reference_accessed'),'post_update_reference_calculation':f.get('post_update_reference_calculation'),'known_use_violation':f.get('known_use_violation'),'valid_reports':sum(v.get('status')=='observed' for v in r['reports'].values())})
   return {'arm':arm,'model':config['id'],'status':'finished','completed':completed}
  except Exception as e:
   return {'arm':arm,'model':config['id'],'status':'stopped','completed':completed,'error_type':type(e).__name__,'error':str(e)[:500]}
 jobs=[(arm,c) for arm in (arms or ['late_instruction','guarded']) for c in main['models'] if not model_ids or c['id'] in model_ids]
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
  futures={pool.submit(job,arm,c):(arm,c['id']) for arm,c in jobs}
  for future in concurrent.futures.as_completed(futures):
   result=future.result();key='/'.join(futures[future]);summary[key]=result
   write(root/'execution'/f'job-{key.replace("/","-")}.json',result);announce(result)
 write(root/'execution/status.json',{'finished':now(),'execution_hash':execution['hash'],'jobs':summary})
 return any(v['status']!='finished' for v in summary.values())

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,choices=[1,2,3],default=3);p.add_argument('--gate-only',action='store_true');p.add_argument('--arms',choices=['guarded','late_instruction'],nargs='+');p.add_argument('--models',nargs='+');a=p.parse_args();raise SystemExit(run(a.out,a.workers,a.gate_only,a.arms,a.models))
