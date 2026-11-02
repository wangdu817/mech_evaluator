"""User-authorized syntax copy, with explicit duplicate thermo policy."""
from pathlib import Path
import argparse,re,json,hashlib,difflib
from collections import defaultdict
from pyteck.respecth.cases import prepare_mechanism

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--thermo-policy',choices=['first','last'],required=True);args=parser.parse_args()
 root=Path(__file__).resolve().parents[1];source=root.parent/'mech/N_CHO_mechanism_2406_revised_240725.inp';thermo=root.parent/'mech/N_CHO_therm_2406.dat';out=root/'results/multi-mechanism/inputs';out.mkdir(parents=True,exist_ok=True)
 original=source.read_text(encoding='utf8');lines=original.splitlines();inside=False;seen=set();duplicates=[];fixed=[]
 for i,line in enumerate(lines):
  content=line.split('!')[0].strip()
  if content.upper()=='SPECIES': inside=True;fixed.append(line);continue
  if inside and content.upper()=='END': inside=False
  if inside:
   species=[]
   for token in content.split():
    if token in seen:duplicates.append({'line':i+1,'species':token})
    else:seen.add(token);species.append(token)
   fixed.append(' '.join(species)+(' !'+line.split('!',1)[1] if '!' in line else ''))
  else:fixed.append(line)
 reaction_copy='\n'.join(fixed)+'\n';reaction_copy=reaction_copy.replace('\nTHERMO\n','\nTHERMO\n0200.00  1000.00  6000.00\n',1)
 # Every selected NASA block is byte-for-byte the corresponding original text block.
 thermo_lines=thermo.read_text(encoding='utf8').splitlines();blocks=defaultdict(list)
 for i,line in enumerate(thermo_lines):
  if not line.lstrip().startswith('!') and len(line)>=80 and line[79:80]=='1':
   name=line[:18].split()[0]
   if name in seen:blocks[name].append((i+1,thermo_lines[i:i+4]))
 chosen={name:entries[0 if args.thermo_policy=='first' else -1] for name,entries in blocks.items()}
 thermo_copy='THERMO ALL\n0200.00  1000.00  6000.00\n'+'\n'.join(line for _,block in chosen.values() for line in block)+'\nEND\n'
 inp=out/'N_CHO_syntax.inp';th=out/'N_CHO_thermo_selected.dat';inp.write_text(reaction_copy,encoding='utf8');th.write_text(thermo_copy,encoding='utf8')
 report={'thermo_policy':args.thermo_policy,'original_inputs':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,thermo)},'duplicate_species_declarations_removed':duplicates,'thermo_selected':{k:{'selected_line':v[0],'alternative_lines':[a for a,b in blocks[k]]} for k,v in chosen.items()},'reaction_section_unchanged':original.split(' REACTIONS',1)[1]==reaction_copy.split(' REACTIONS',1)[1],'NASA_blocks_unchanged':True,'header_temperature_range_source':str(thermo)+':2','scope':'working syntax copy; original mechanism and thermo read-only'}
 assert report['reaction_section_unchanged']
 (out/'mechanism.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),reaction_copy.splitlines(True),fromfile=str(source),tofile=str(inp))),encoding='utf8')
 (out/'thermo.diff').write_text(''.join(difflib.unified_diff(thermo.read_text(encoding='utf8').splitlines(True),thermo_copy.splitlines(True),fromfile=str(thermo),tofile=str(th))),encoding='utf8')
 (out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 m=prepare_mechanism({'id':'N_CHO_240725','path':str(inp),'thermo':str(th),'prepared_dir':str(out.parent/'prepared')})
 print('Loaded working copy:',len(m.species),'species;',m.path)
if __name__=='__main__':main()
