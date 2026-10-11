"""Step 1: mine git history for incident signals around PostgreSQL migrations (no API)."""
import subprocess, sys, os, re, json, glob
sys.path.insert(0, glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'venv/lib/python*/site-packages'))[0])
from ekbasis.migrations import is_migration
NONPG = re.compile(r"(mysql|sqlite|clickhouse|testdata|cockroach|mssql)", re.I)
MSG = re.compile(r"revert|hotfix|hot-fix|rollback|roll back|broke|broken|fail|data loss|lost|not null|constraint|"
                 r"duplicate|unique|deadlock|lock|timeout|downtime|incident|outage|\bfix|repair|restore|undo|corrupt|"
                 r"wrong|bad migration|prod", re.I)
NAME = re.compile(r"fix|revert|repair|hotfix|correct|restore|undo|rollback|dedup|cleanup|backfill", re.I)
out = []
for r in sorted(os.listdir('repos')):
    p = os.path.join('repos', r)
    if not os.path.isdir(p): continue
    log = subprocess.run(['git', '-C', p, 'log', '--first-parent', '--no-renames', '--name-status',
                          '--format=%x00%H%x09%P%x09%aI%x09%s'], capture_output=True, text=True, errors='replace').stdout
    for blk in log.split('\x00')[1:]:
        lines = blk.strip('\n').split('\n')
        h, par, date, subj = (lines[0].split('\t') + ['', '', '', ''])[:4]
        files = [l.split('\t') for l in lines[1:] if '\t' in l]
        mig = [(s, f) for s, f in files if is_migration(f) and not NONPG.search(f)]
        if not mig: continue
        added = [f for s, f in mig if s == 'A']; mod = [f for s, f in mig if s == 'M']; dele = [f for s, f in mig if s == 'D']
        sig = []
        if MSG.search(subj): sig.append('msg')
        if mod: sig.append('edit')
        if dele: sig.append('delete')
        if any(NAME.search(os.path.dirname(f) + os.path.basename(f)) for f in added): sig.append('name')
        if sig:
            out.append(dict(repo=r, sha=h, parent=par.split()[0] if par else None, date=date[:10], subj=subj,
                            added=added, modified=mod, deleted=dele, signals=sig))
json.dump(out, open('mined.json', 'w'), indent=0)
import collections
print(len(out), collections.Counter(o['repo'] for o in out))
