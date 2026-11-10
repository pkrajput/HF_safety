"""Bounded concurrent collection for the frozen restored task protocol."""
import argparse,concurrent.futures,hashlib,json
from pathlib import Path
from . import late_faithful
from .concurrent_client import ConcurrentClient,budget_allows_new_requests
from .runner import write,now,digest

def run(root,workers=3):
 root=Path(root);m=json.loads((root/'late_faithful/manifest.json').read_text())
 b=json.loads((root/'budget.json').read_text())
 if any(v['status']=='pending' for v in b['requests'].values()) or not budget_allows_new_requests(b):raise RuntimeError('Reconcile prior pending/unknown requests before starting')
 late_faithful.Client=ConcurrentClient
 record={'time':now(),'workers':workers,'manifest_hash':m['hash'],'shared_cap_usd':9.0,'transport':'ConcurrentClient; original API payload conversion preserved; timeout600seconds; unknown observations not retried','source_hashes':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in ['faithful_parallel.py','concurrent_client.py']}}
 write(root/'late_faithful/execution'/f'{digest(record)[:16]}.json',record)
 results={}
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
  jobs={pool.submit(late_faithful.run,root,c['id']):c['id'] for c in m['models']}
  for job in concurrent.futures.as_completed(jobs):
   name=jobs[job]
   try:results[name]={'failed':bool(job.result())}
   except Exception as exc:results[name]={'failed':True,'error_type':type(exc).__name__,'error':str(exc)[:300]}
   print(json.dumps({'model':name,**results[name]}),flush=True)
 write(root/'late_faithful/execution/status.json',{'finished':now(),'models':results})
 return any(x['failed'] for x in results.values())
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,choices=[1,2,3],default=3);a=p.parse_args();raise SystemExit(run(a.out,a.workers))
