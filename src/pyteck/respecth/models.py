"""Lossless experimental identities and serializable simulation contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import hashlib
import json
import math
from ..path_io import absolute_path

SCHEMA_VERSION = 1
KINDS = {
    "outlet concentration measurement": "pfr",
    "jet stirred reactor measurement": "jsr",
    "ignition delay measurement": "ignition",
    "laminar burning velocity measurement": "flame",
    "concentration time profile measurement": "profile",
    "burner stabilized flame speciation measurement": "burner_profile",
}
OBSERVABLES = {"composition", "concentration", "ignition delay", "laminar burning velocity"}


def digest(value: Any) -> str:
    def canonical(item):
        if isinstance(item, float) and not math.isfinite(item):
            return {"invalid_numeric": str(item)}
        if isinstance(item, dict):
            return {key: canonical(v) for key, v in item.items()}
        if isinstance(item, (tuple, list)):
            return [canonical(v) for v in item]
        return item
    return hashlib.sha256(json.dumps(canonical(value), sort_keys=True, ensure_ascii=False,
                                      allow_nan=False, default=str).encode()).hexdigest()


def file_hash(path: str | Path) -> str:
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


@dataclass
class Property:
    id: str
    name: str
    units: str = ""
    species: str | None = None
    label: str = ""
    source_type: str = ""
    attrs: dict = field(default_factory=dict)
    value: float | None = None
    components: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)


@dataclass
class Condition:
    scan_name: str
    scan_value: float
    temperature: float | None
    pressure: float | None
    composition: dict[str, float]
    residence_time: float | None = None
    volume: float | None = None
    extras: dict = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


@dataclass
class ObservationSeries:
    id: str
    group_id: str
    property_id: str
    quantity: str
    species: str | None
    instrument: str
    units: str
    source_type: str
    label: str
    scan_name: str
    x: list[float]
    y: list[float]
    raw_values: list[float]
    point_indices: list[int]
    uncertainty: list[float | None] = field(default_factory=list)


@dataclass
class DataGroup:
    id: str
    label: str
    properties: list[Property]
    points: list[dict[str, float]]
    conditions: list[Condition]
    scan_name: str


@dataclass
class Experiment:
    id: str
    path: str
    sha256: str
    version: str
    experiment_type: str
    apparatus: dict
    bibliography: dict
    common_properties: list[Property]
    groups: list[DataGroup]
    observations: list[ObservationSeries]
    ignition_type: dict = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    xml_text: str = ""

    @property
    def kind(self):
        return KINDS.get(self.experiment_type, "unsupported")


@dataclass
class Mechanism:
    id: str
    path: str
    phase: str
    sha256: str
    species_map: dict[str, str]
    species: list[str]
    transport: bool
    provenance: dict = field(default_factory=dict)


@dataclass
class SimulationCase:
    id: str
    experiment_id: str
    group_id: str
    point_indices: list[int]
    kind: str
    condition: Condition
    mechanism: Mechanism
    config: dict
    targets: list[dict]
    role: str = "scoring"
    issues: list[str] = field(default_factory=list)
    predecessor: str | None = None


@dataclass
class CaseResult:
    case_id: str
    status: str
    predictions: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    history_path: str = ""
    validation: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class RunConfig:
    datasets: list[str]
    mechanisms: list[dict]
    output: str
    schema_version: int = SCHEMA_VERSION
    dataset_configs: dict = field(default_factory=dict)
    solver: dict = field(default_factory=dict)
    grid: dict = field(default_factory=dict)
    scoring: dict = field(default_factory=dict)
    figure: dict = field(default_factory=dict)
    workers: int = 0
    flame_workers: int = 2
    retry_failed: bool = False
    reuse_results: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, base: Path | None = None):
        data = clean_obsolete_options(data)
        if data.get("schema_version", 1) != SCHEMA_VERSION:
            raise ValueError("Unsupported configuration schema_version")
        root = base or Path.cwd()
        def resolve(p):
            path = Path(p).expanduser()
            return str(absolute_path(root / path if not path.is_absolute() else path))
        data["datasets"] = [resolve(p) for p in data["datasets"]]
        data["output"] = resolve(data["output"])
        data["reuse_results"] = [resolve(p) for p in data.get("reuse_results", [])]
        data["mechanisms"] = [dict(m) for m in data["mechanisms"]]
        for mechanism in data["mechanisms"]:
            for key in ("path", "thermo", "transport"):
                if mechanism.get(key):
                    mechanism[key] = resolve(mechanism[key])
        if not data["datasets"] or not data["mechanisms"]:
            raise ValueError("Select at least one dataset and mechanism")
        ids = [m["id"] for m in data["mechanisms"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Mechanism IDs must be unique")
        if data.get("workers", 0) < 0 or data.get("flame_workers", 2) < 1:
            raise ValueError("Invalid worker limits")
        return cls(**data)

    def to_dict(self):
        return asdict(self)


DEFAULT_SOLVER = {
    "rtol": 1e-9, "atol": 1e-15, "verify": True,
    "validation_relative": .01, "validation_absolute": 1e-10,
    "steady_threshold": 1e-6, "steady_floor": 1e-8,
    "initialization": "independent", "transport_model": "mixture-averaged",
    "soret": False, "width": .03, "flame_max_rounds": 3,
    "energy": "off",
}


def clean_obsolete_options(value):
    """Accept old configs while discarding retired concentration normalization."""
    if isinstance(value, dict):
        return {k:clean_obsolete_options(v) for k,v in value.items()
                if k not in {'concentration_basis','measurement_basis_confirmed','basis_source'}}
    if isinstance(value,list): return [clean_obsolete_options(v) for v in value]
    return value


def finite(value):
    return isinstance(value, (float, int)) and math.isfinite(value)


def result_from_dict(data):
    return CaseResult(**data)


def case_from_dict(data):
    data = dict(data)
    data["condition"] = Condition(**data["condition"])
    data["mechanism"] = Mechanism(**data["mechanism"])
    return SimulationCase(**data)
