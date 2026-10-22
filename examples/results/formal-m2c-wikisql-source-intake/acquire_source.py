import hashlib,json,urllib.request
from pathlib import Path
root=Path('runs/wikisql-source-20261023')
root.mkdir(parents=True,exist_ok=False)
revision='cffb423077756d04c1bac5bcd45167c86903fbcb'
assets=[('LICENSE','504143ed33b21e59b4cb8a392c03268b10cdd233',1519),('README.md','0106898203a175db2d9b40ee257c02c2373a996c',19686),('data.tar.bz2','941de4cb2ad5fa7aeb2e37d314468636ce070af7',26164664)]
manifest={'kind':'pinned_external_source_acquisition','repository':'salesforce/WikiSQL','revision':revision,'status':'running','assets':[]}
def save(): (root/'acquisition.json').write_text(json.dumps(manifest,indent=2)+'\n')
save()
try:
 for name,expected,size in assets:
  url=f'https://raw.githubusercontent.com/salesforce/WikiSQL/{revision}/{name}'
  sha256=hashlib.sha256();blob=hashlib.sha1(f'blob {size}\0'.encode());count=0
  part=root/(name+'.part')
  with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'IntentLab-source-intake'}),timeout=30) as response,part.open('xb') as stream:
   while chunk:=response.read(1024*1024):
    count+=len(chunk)
    if count>size: raise ValueError('Source exceeds expected Git blob size')
    stream.write(chunk);sha256.update(chunk);blob.update(chunk)
  if count!=size or blob.hexdigest()!=expected: raise ValueError('Pinned Git blob mismatch: '+name)
  part.rename(root/name)
  manifest['assets'].append({'path':name,'url':url,'bytes':count,'git_blob_sha1':expected,'sha256':sha256.hexdigest()});save()
  print(json.dumps(manifest['assets'][-1]),flush=True)
 manifest['status']='completed';save()
except Exception as e:
 manifest.update(status='failed',error_type=type(e).__name__,error=str(e));save();raise
