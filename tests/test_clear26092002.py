"""Audit real mechanism conversion and resolved Cantera rate preservation."""
from pathlib import Path
import hashlib,json
import numpy as np
import cantera as ct
from pyteck.respecth.cases import prepare_mechanism

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'results/clear-26092002'

def test_source_and_nasa_blocks_preserved():
    audit=json.loads((BASE/'inputs/audit.json').read_text(encoding='utf8'))
    for path,value in audit['source_hashes'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==value
    thermo=next(Path(p) for p in audit['source_hashes'] if p.endswith('thermo.dat'))
    original=thermo.read_text(encoding='utf8').splitlines()
    selected=(BASE/'inputs/thermo_selected.dat').read_text(encoding='utf8')
    for entry in audit['thermo_selection'].values():
        assert '\n'.join(original[entry['line']-1:entry['line']+3]) in selected
    assert len(audit['syntax_changes'])==6
    assert [c['line'] for c in audit['syntax_changes']]==[178,7465,7466,7467,7468,7469]
    assert not audit['kinetic_parameter_changes']

def test_resolved_mechanism_retains_all_rates(tmp_path):
    source=BASE/'prepared/26092002_converted.yaml'
    original=ct.Solution(yaml=source.read_text(encoding='utf8'))
    mechanism=prepare_mechanism({'id':'clear','path':str(source),'prepared_dir':str(tmp_path)})
    resolved=ct.Solution(yaml=Path(mechanism.path).read_text(encoding='utf8'))
    assert original.n_species==resolved.n_species==199
    assert original.n_reactions==resolved.n_reactions==1881
    for T,P in [(700,1),(1300,1.3),(2000,10)]:
        for gas in (original,resolved):gas.TPX=T,P*ct.one_atm,'CH3NH2:0.02,O2:0.055,AR:0.925'
        np.testing.assert_allclose(original.forward_rate_constants,resolved.forward_rate_constants,rtol=1e-12,atol=0)
        np.testing.assert_allclose(original.standard_enthalpies_RT,resolved.standard_enthalpies_RT,rtol=1e-12,atol=1e-12)
    assert not mechanism.transport

def test_transport_shortfall_explicit():
    audit=json.loads((BASE/'inputs/audit.json').read_text(encoding='utf8'))
    assert len(audit['transport_missing'])==13
    assert audit['transport_model']=='none'
    assert audit['transport_duplicates']=={'NCNOH':[17,519]}
