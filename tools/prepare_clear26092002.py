"""Audited, source-preserving CHEMKIN syntax copies for 26092002_clear."""
from pathlib import Path
from collections import defaultdict
import re, json, hashlib, difflib, contextlib, io
from cantera.ck2yaml import convert
import cantera as ct

root=Path(__file__).resolve().parents[1]
source=root.parent/'mech/26092002_clear.inp'
paired=root.parent.parent/'MECH'
thermo=paired/'thermo.dat'; transport=root.parent/'mech/trans.dat'
out=root/'results/clear-26092002/inputs';out.mkdir(parents=True,exist_ok=True)
assert source.read_bytes()==(paired/source.name).read_bytes()
original=source.read_text(encoding='utf8'); lines=original.splitlines(); changes=[]; fixed=[]
inside=False;species=[]
for i,line in enumerate(lines):
    content=line.split('!')[0].strip()
    if content=='SPECIES': inside=True
    elif inside and content=='END':inside=False
    elif inside:species.extend(content.split())
    active,sep,comment=line.partition('!')
    active=re.sub(r'\s+MAXSP=\d+','',active) if active.lstrip().startswith('REACTIONS') else active
    active=re.sub(r'(?<![\w.])([+-]?\d+\.\d+)([+-]\d+)(?![\d.])',r'\1E\2',active)
    newer=active+(sep+comment if sep else '')
    if newer!=line: changes.append({'line':i+1,'before':line,'after':newer,'kind':'syntax'})
    fixed.append(newer)
assert len(species)==len(set(species))
blocks=defaultdict(list);tlines=thermo.read_text(encoding='utf8').splitlines()
for i,line in enumerate(tlines[:-3]):
    if line.lstrip().startswith('!') or not line.strip(): continue
    if all(re.search(r'\s'+str(j+2)+r'\s*$',tlines[i+j+1].split('!')[0]) for j in range(3)):
        name=line.split()[0]
        if name in species:blocks[name].append((i+1,tlines[i:i+4]))
missing=set(species)-set(blocks)
assert not missing,missing
selected={s:blocks[s][0] for s in species}
thtext='THERMO ALL\n'+tlines[1]+'\n'+'\n'.join(line for _,block in selected.values() for line in block)+'\nEND\n'
trlines=transport.read_text(encoding='utf8').splitlines();tr=defaultdict(list)
for i,line in enumerate(trlines):
    tokens=line.split('!')[0].split()
    if tokens and tokens[0] in species:tr[tokens[0]].append((i+1,line))
trmissing=sorted(set(species)-set(tr))
inp=out/'26092002_syntax.inp';th=out/'thermo_selected.dat';trp=out/'transport_selected.dat'
inp.write_text('\n'.join(fixed)+'\n',encoding='utf8');th.write_text(thtext,encoding='utf8')
trp.write_text('\n'.join(tr[s][0][1] for s in species if s in tr)+'\n',encoding='utf8')
report={'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,thermo,transport)},
    'paired_mechanism_identical':True,'species':len(species),'syntax_changes':changes,
    'thermo_policy':'first','thermo_selection':{s:{'line':v[0],'alternatives':[a for a,b in blocks[s]]} for s,v in selected.items()},
    'transport_policy':'first','transport_missing':trmissing,'transport_duplicates':{s:[v[0] for v in rows] for s,rows in tr.items() if len(rows)>1},
    'NASA_blocks_unchanged':True,'kinetic_parameter_changes':False}
for name,old,new in [('mechanism',original,inp.read_text(encoding='utf8')),('thermo',thermo.read_text(encoding='utf8'),thtext),('transport',transport.read_text(encoding='utf8'),trp.read_text(encoding='utf8'))]:
    (out/(name+'.diff')).write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True))),encoding='utf8')
(out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
prepared=out.parent/'prepared';prepared.mkdir(exist_ok=True)
stream=io.StringIO()
try:
    with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
        convert(input_file=str(inp),thermo_file=str(th),transport_file=str(trp) if not trmissing else None,
                out_name=str(prepared/'26092002_converted.yaml'),permissive=False)
finally:(prepared/'conversion.log').write_text(stream.getvalue(),encoding='utf8')
gas=ct.Solution(yaml=(prepared/'26092002_converted.yaml').read_text(encoding='utf8'))
report.update(cantera_version=ct.__version__,loaded_species=gas.n_species,loaded_reactions=gas.n_reactions,
              transport_model=gas.transport_model,converted_yaml_sha256=hashlib.sha256((prepared/'26092002_converted.yaml').read_bytes()).hexdigest())
assert gas.n_species==len(species)
(out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(gas.n_species,gas.n_reactions,gas.transport_model)
