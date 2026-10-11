import subprocess, sys, collections, os
sys.path.insert(0, [p for p in __import__('glob').glob(os.path.join(os.path.dirname(os.path.abspath(__file__)),'venv/lib/python*/site-packages'))][0])
from ekbasis.migrations import is_migration, set_dir, tool_of
for r in sorted(os.listdir('repos')):
    p=os.path.join('repos',r)
    if not os.path.isdir(p): continue
    out=subprocess.run(['git','-C',p,'ls-tree','-r','--name-only','HEAD'],capture_output=True,text=True).stdout.split()
    c=collections.Counter((set_dir(f),tool_of(f)) for f in out if is_migration(f))
    print(r, [(k,v) for k,v in c.most_common(6)])
