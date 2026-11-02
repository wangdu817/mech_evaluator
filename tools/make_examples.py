"""Generate explicitly synthetic H2 examples; never touches experimental inputs."""
from pathlib import Path
import json
import xml.etree.ElementTree as ET

import cantera as ct
import yaml

PROJECT = Path(__file__).resolve().parents[1]
destination = PROJECT / "examples" / "respecth"
destination.mkdir(parents=True, exist_ok=True)
mechanism_dir = destination / "mechanisms"
mechanism_dir.mkdir(exist_ok=True)
for name in ("h2o2", "gri30"):
    if not (mechanism_dir / f"{name}.yaml").exists():
        gas = ct.Solution(f"{name}.yaml")
        (mechanism_dir / f"{name}.yaml").write_text(gas.write_yaml(), encoding="utf-8")

definitions = {
    "pfr": ("outlet concentration measurement", "flow reactor", [700, 1000], [("composition", "H2", "mole fraction", [.1, .03]), ("composition", "H2O", "mole fraction", [.001, .08])]),
    "jsr": ("jet stirred reactor measurement", "stirred reactor", [700, 1000], [("composition", "H2", "mole fraction", [.1, .02]), ("composition", "H2O", "mole fraction", [.001, .1])]),
    "ignition": ("ignition delay measurement", "shock tube", [1000, 1100, 1200], [("ignition delay", None, "s", [.0005, .00015, .00006])]),
    "flame": ("laminar burning velocity measurement", "flame", [298, 298, 298], [("laminar burning velocity", None, "cm/s", [150., 200., 220.])]),
}
for kind, (experiment_type, apparatus, temperatures, measurements) in definitions.items():
    root = ET.Element("experiment")
    ET.SubElement(root, "fileAuthor").text = "Software validation fixture, not experimental measurements"
    for tag, major, minor in (("fileVersion", 1, 0), ("ReSpecThVersion", 2, 6)):
        version = ET.SubElement(root, tag)
        ET.SubElement(version, "major").text = str(major)
        ET.SubElement(version, "minor").text = str(minor)
    ET.SubElement(root, "experimentType").text = experiment_type
    apparatus_node = ET.SubElement(root, "apparatus")
    ET.SubElement(apparatus_node, "kind").text = apparatus
    common = ET.SubElement(root, "commonProperties")
    for name, unit, value in [("pressure", "atm", 1), ("residence time", "s", .05), ("volume", "cm3", 30)]:
        prop = ET.SubElement(common, "property", name=name, units=unit, sourcetype="calculated")
        ET.SubElement(prop, "value").text = str(value)
    inlet = ET.SubElement(common, "property", name="initial composition", sourcetype="calculated")
    composition = {"H2": 2/3.0/6, "O2": 1/3.0/6, "AR": 5/6}
    if kind == "flame":
        composition = {"H2": 2/6.76, "O2": 1/6.76, "N2": 3.76/6.76}
    for species, value in composition.items():
        comp = ET.SubElement(inlet, "component")
        ET.SubElement(comp, "speciesLink", preferredKey=species)
        ET.SubElement(comp, "amount", units="mole fraction").text = str(value)
    group = ET.SubElement(root, "dataGroup", id="dg1", label="Synthetic software fixture")
    ET.SubElement(group, "property", name="temperature", id="T_column", label="T", units="K", sourcetype="calculated")
    for j, (quantity, species, unit, values) in enumerate(measurements):
        prop = ET.SubElement(group, "property", name=quantity, id=f"obs{j}", units=unit,
                             label=(species or quantity), sourcetype="calculated")
        if species:
            ET.SubElement(prop, "speciesLink", preferredKey=species)
    for i, temperature in enumerate(temperatures):
        point = ET.SubElement(group, "dataPoint")
        ET.SubElement(point, "T_column").text = str(temperature)
        for j, (_, _, _, values) in enumerate(measurements):
            ET.SubElement(point, f"obs{j}").text = str(values[i])
    if kind == "ignition":
        ET.SubElement(root, "ignitionType", target="p", type="d/dt max")
    if kind == "flame":
        common.remove(inlet)
        ET.SubElement(group, "property", name="equivalence ratio", id="phi_column", label="phi", units="unitless", sourcetype="calculated")
        for species in ("H2", "O2", "N2"):
            prop = ET.SubElement(group, "property", name="initial composition", id=f"in_{species}", units="mole fraction", sourcetype="calculated")
            ET.SubElement(prop, "speciesLink", preferredKey=species)
        for point, phi in zip(group.findall("dataPoint"), [.8, 1., 1.2]):
            ET.SubElement(point, "phi_column").text = str(phi)
            for species, amount in {"H2": 2*phi, "O2": 1, "N2": 3.76}.items():
                ET.SubElement(point, f"in_{species}").text = str(amount/(2*phi+4.76))
    ET.SubElement(root, "comment").text = "SYNTHETIC: nominal y values exercise software scoring only. They are not experiments and cannot validate a kinetic mechanism."
    ET.indent(root)
    ET.ElementTree(root).write(destination / f"synthetic-{kind}.xml", encoding="utf-8", xml_declaration=True)

second = ET.parse(destination / "synthetic-ignition.xml")
second.find("commonProperties/property[@name='pressure']/value").text = "2"
second.write(destination / "synthetic-ignition-2atm.xml", encoding="utf-8", xml_declaration=True)

config = {
    "schema_version": 1,
    "datasets": [f"synthetic-{k}.xml" for k in definitions] + ["synthetic-ignition-2atm.xml"],
    "mechanisms": [{"id": name, "path": f"mechanisms/{name}.yaml"} for name in ("h2o2", "gri30")],
    "output": "../../results/demo", "solver": {"concentration_basis": "wet", "verify": True},
    "grid": {"enabled": False}, "figure": {}, "scoring": {}, "workers": 2,
}
(destination / "demo.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

local_files = [p for folder in PROJECT.parent.glob("exp*") if folder.is_dir() for p in folder.glob("*.xml")]
local = {"schema_version": 1, "datasets": [str(p.resolve()) for p in sorted(local_files)],
    "mechanisms": [{"id": "user_mechanism", "path": "D:/path/mechanism.yaml", "species_map": {}}],
    "output": "../../results/local-library", "solver": {"verify": True},
    "dataset_configs": {}, "grid": {"enabled": True}, "scoring": {}, "figure": {}, "workers": 0}
for path in local_files:
    overrides = {"energy": "off", "concentration_basis": "dry" if path.parent.name == "exp5" else "unknown"}
    coefficient = {"exp1": 195, "exp5": 203, "exp6": 93.3, "exp7": 195}.get(path.parent.name)
    if coefficient:
        overrides["grid_rules"] = {"residence_time": {"kind": "inverse_temperature", "coefficient": coefficient}}
        overrides["model_source"] = "Source publication reports isothermal flow reactor; original XML supplies pointwise tau"
    if path.parent.name == "exp5":
        overrides["basis_source"] = "Hjuler 1995 explicitly reports dry gas basis"
    local["dataset_configs"][str(path.resolve())] = overrides
(destination / "local-library.yaml").write_text(yaml.safe_dump(local, allow_unicode=True, sort_keys=False), encoding="utf-8")
print(json.dumps({"directory": str(destination), "local_xml": len(local_files)}, ensure_ascii=False))
