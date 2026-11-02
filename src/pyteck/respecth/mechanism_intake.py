"""Audited homepage conversion and independent Cantera load validation."""
from pathlib import Path
from datetime import datetime, timezone
import warnings
from .cases import prepare_mechanism
from .models import digest, file_hash
from .atomic_io import atomic_json


def validate_mechanism_input(entry, directory):
    directory = Path(directory)
    identity = {key: {'path':str(Path(entry[key]).resolve()), 'hash':file_hash(entry[key])}
                for key in ('path','thermo','transport') if entry.get(key)}
    identity.update(phase=entry.get('phase',''), species_map=entry.get('species_map',{}))
    conversion_options = {'permissive': entry.get('permissive', True)} if Path(entry['path']).suffix.lower()=='.inp' else {}
    identity['conversion_options'] = conversion_options
    record_path = directory/f'validation-{digest(identity)}.json'
    record = {'inputs':identity, 'conversion_options':conversion_options,
              'updated_utc':datetime.now(timezone.utc).isoformat()}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        try:
            prepared = prepare_mechanism({**entry, 'prepared_dir':str(directory)})
            record.update(status='success', phase=prepared.phase, species=len(prepared.species),
                          transport=prepared.transport, working_yaml=prepared.path,
                          conversion_log=prepared.provenance.get('conversion_log',''))
        except Exception as exc:
            record.update(status='failed', error=str(exc))
            raise
        finally:
            record['warnings'] = list(dict.fromkeys(str(w.message) for w in caught))
            atomic_json(record_path, record)
    return prepared, {**record, 'record_path':str(record_path)}
