from pathlib import Path
import json
import cantera as ct
import pytest
from pyteck.respecth.mechanism_intake import validate_mechanism_input


def test_real_chemkin_conversion_and_source_preservation(tmp_path):
    root = Path(__file__).resolve().parents[1]
    from pyteck.respecth.models import file_hash
    from pyteck.respecth.cases import prepare_mechanism
    source = root.parent/'mech'
    entry = {'id':'third', 'path':str(source/'Mech25_47_v1_NH3_CH4_260324_MECH.inp'),
        'thermo':str(source/'Mech25_47_v1_NH3_CH4_260324_THERM.dat'),
        'transport':str(source/'Mech25_47_v1_NH3_CH4_260324_TRAN.dat'), 'species_map':{'Ar':'AR'}}
    before = {key:file_hash(entry[key]) for key in ('path','thermo','transport')}
    mechanism, audit = validate_mechanism_input(entry, tmp_path)
    assert audit['status']=='success' and audit['species']==194 and audit['transport']
    assert mechanism.sha256 == prepare_mechanism({**entry,'prepared_dir':str(tmp_path/'other')}).sha256
    assert all(file_hash(entry[key])==value for key,value in before.items())
    assert json.loads(Path(audit['record_path']).read_text())['status']=='success'


def test_bad_chemkin_fails_with_audit_and_log(tmp_path):
    bad = tmp_path/'bad.inp'
    bad.write_text('ELEMENTS\nH O\nEND\nSPECIES\nH2 O2\nEND\nREACTIONS\nH2 => O2 invalid\nEND\n')
    thermo = tmp_path/'thermo.dat'
    thermo.write_text('THERMO ALL\n300.0 1000.0 5000.0\nEND\n')
    with pytest.raises(Exception):
        validate_mechanism_input({'id':'bad','path':str(bad),'thermo':str(thermo)}, tmp_path/'prepared')
    records = list((tmp_path/'prepared').glob('validation-*.json'))
    assert len(records)==1
    assert json.loads(records[0].read_text())['status']=='failed'
    assert list((tmp_path/'prepared').glob('conversion-*.log'))


def test_default_permissive_accepts_redundant_thermo_and_records_log(tmp_path):
    from cantera.yaml2ck import convert
    from pyteck.respecth.gas_io import load_gas
    from pyteck.respecth.models import file_hash
    gas = load_gas(Path(__file__).resolve().parents[1] / 'examples/respecth/mechanisms/h2o2.yaml')
    source, thermo = tmp_path/'mechanism.inp', tmp_path/'thermo.dat'
    convert(gas, mechanism_path=source, thermo_path=thermo, overwrite=True)
    lines = thermo.read_text().splitlines()
    first = next(i for i, line in enumerate(lines) if len(line) >= 80 and line[79] == '1')
    end = max(i for i, line in enumerate(lines) if line.strip().upper() == 'END')
    lines[end:end] = lines[first:first+4]
    thermo.write_text('\n'.join(lines)+'\n')
    entry = {'id':'redundant', 'path':str(source), 'thermo':str(thermo)}
    before = {key:file_hash(entry[key]) for key in ('path','thermo')}
    prepared, audit = validate_mechanism_input(entry, tmp_path/'prepared')
    assert audit['status'] == 'success'
    assert audit['conversion_options'] == {'permissive':True}
    assert prepared.provenance['conversion_options'] == {'permissive':True}
    assert 'Ignoring redundant thermo data' in audit['conversion_log']
    assert 'permissive=True' in audit['conversion_log']
    loaded = load_gas(prepared.path)
    assert loaded.n_species == gas.n_species and loaded.n_reactions == gas.n_reactions
    gas.TP = loaded.TP = 1000, ct.one_atm
    assert loaded.forward_rate_constants == pytest.approx(gas.forward_rate_constants)
    assert loaded.standard_enthalpies_RT == pytest.approx(gas.standard_enthalpies_RT)
    with pytest.raises(Exception):
        validate_mechanism_input({**entry,'permissive':False}, tmp_path/'prepared')
    records = [json.loads(p.read_text()) for p in (tmp_path/'prepared').glob('validation-*.json')]
    assert len(records) == 2
    assert {r['status'] for r in records} == {'failed','success'}
    assert all(file_hash(entry[key]) == value for key,value in before.items())


def test_conversion_rejects_non_boolean_permissive(tmp_path):
    from pyteck.respecth.cases import prepare_mechanism
    source = tmp_path/'bad.inp'; source.write_text('END\n')
    with pytest.raises(ValueError, match='permissive must be true or false'):
        prepare_mechanism({'id':'invalid','path':str(source),'permissive':'false',
                           'prepared_dir':str(tmp_path/'prepared')})


def test_clean_mechanism_identity_independent_of_conversion_policy(tmp_path):
    from cantera.yaml2ck import convert
    from pyteck.respecth.gas_io import load_gas
    from pyteck.respecth.cases import prepare_mechanism
    gas = load_gas(Path(__file__).resolve().parents[1] / 'examples/respecth/mechanisms/h2o2.yaml')
    source, thermo = tmp_path/'clean.inp', tmp_path/'thermo.dat'
    convert(gas, mechanism_path=source, thermo_path=thermo, overwrite=True)
    entry = {'id':'clean','path':str(source),'thermo':str(thermo),'prepared_dir':str(tmp_path/'prepared')}
    default = prepare_mechanism(entry)
    strict = prepare_mechanism({**entry,'permissive':False})
    assert default.sha256 == strict.sha256
    assert default.species == strict.species
    assert len(list((tmp_path/'prepared').glob('conversion-*.log'))) == 2
