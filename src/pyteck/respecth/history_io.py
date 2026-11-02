"""Append full adaptive histories to disk with a bounded row buffer."""
from pathlib import Path
import uuid
import h5py
import numpy as np


class DiskHistory:
    scalar_names = ('time', 'temperature', 'pressure', 'volume')
    vector_names = ('mole_fractions', 'mass_fractions', 'concentrations')

    def __init__(self, directory, species_count, buffer_rows=256):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / ('.history-'+uuid.uuid4().hex+'.h5.tmp')
        self.file = h5py.File(self.path, 'w')
        self.file.attrs['complete'] = False
        self.buffer_rows = buffer_rows
        self.buffer = []
        self.rows_written = 0
        self.species_count = species_count
        for name in self.scalar_names:
            self.file.create_dataset(name, shape=(0,), maxshape=(None,), chunks=(buffer_rows,), dtype='f8', compression='gzip')
        for name in self.vector_names:
            self.file.create_dataset(name, shape=(0,species_count), maxshape=(None,species_count),
                                     chunks=(buffer_rows,species_count), dtype='f8', compression='gzip')

    @property
    def buffered_bytes(self):
        return sum(32 + sum(v.nbytes for v in row[4:]) for row in self.buffer)

    def record(self, reactor, elapsed):
        phase = reactor.phase
        self.buffer.append((float(elapsed), float(reactor.T), float(phase.P), float(reactor.volume),
                            phase.X.copy(), phase.Y.copy(), phase.concentrations.copy()*1000))
        if len(self.buffer) >= self.buffer_rows:
            self.flush()

    def flush(self):
        if not self.buffer:
            return
        end = self.rows_written+len(self.buffer)
        for index, name in enumerate(self.scalar_names+self.vector_names):
            dataset = self.file[name]
            dataset.resize(end, axis=0)
            dataset[self.rows_written:end] = np.asarray([r[index] for r in self.buffer])
        self.rows_written = end
        self.buffer.clear()
        self.file.flush()

    def __getitem__(self, name):
        self.flush()
        return self.file[name]

    def finish(self, destination, attrs):
        self.flush()
        for name, value in attrs.items():
            self.file.attrs[name] = value
        self.file.attrs['complete'] = True
        self.file.flush()
        self.file.close()
        self.path.replace(destination)

    def close(self):
        if self.file.id.valid:
            self.file.close()
        # Remove only this object's unique unfinished work file.
        self.path.unlink(missing_ok=True)
