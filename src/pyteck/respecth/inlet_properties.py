"""Derived inlet properties for display, without modifying simulation inputs."""
from functools import lru_cache
from pathlib import Path
import re
import math
from .gas_io import load_gas


@lru_cache(maxsize=16)
def _atoms(path, phase, stamp, size):
    gas=load_gas(path,phase)
    return {s:{e:gas.n_atoms(s,e) if e in gas.element_names else 0.
               for e in ('C','H','O','S')} for s in gas.species_names}


def inlet_equivalence_ratio(condition, mechanism=None):
    """Cantera's total-element oxygen required / oxygen available definition.

    N is treated as N2; O bound in NO/H2O/CO2 is included, as in the
    no-stream-arguments Cantera definition. No fuel/oxidizer streams guessed.
    """
    composition=condition.composition
    if not composition or any(not math.isfinite(x) or x<0 for x in composition.values()):
        raise ValueError('Invalid inlet mole fractions')
    if mechanism:
        path=Path(mechanism.path);stat=path.stat()
        atoms=_atoms(str(path),mechanism.phase,stat.st_mtime_ns,stat.st_size)
        aliases=mechanism.species_map
    else:
        atoms={};aliases={}
        # Only unambiguous molecular formulas when no mechanism is available.
        for species in composition:
            if species.upper() in {'AR','HE'}: atoms[species]={};continue
            tokens=re.findall(r'([CHONS])(\d*)',species)
            if ''.join(e+n for e,n in tokens)!=species:
                raise ValueError(f'Elemental composition unavailable: {species}')
            atom={}
            for element,count in tokens: atom[element]=atom.get(element,0)+int(count or 1)
            atoms[species]=atom
    totals={e:0. for e in ('C','H','O','S')}
    for species,x in composition.items():
        if x==0: continue
        name=aliases.get(species,species)
        if name not in atoms: raise ValueError(f'Elemental composition unavailable: {species}')
        for element in totals: totals[element]+=x*atoms[name].get(element,0.)
    if totals['O']<=0: raise ValueError('No available oxygen; equivalence ratio undefined')
    return (2*totals['C']+.5*totals['H']+2*totals['S'])/totals['O']
