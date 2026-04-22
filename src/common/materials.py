from __future__ import annotations

from typing import Dict


def build_materials(openmc_module) -> Dict[str, object]:
    """Create a conservative default material map keyed by DAGMC tags."""

    blanket = openmc_module.Material(name="blanket")
    blanket.set_density("g/cm3", 10.0)
    blanket.add_element("Li", 0.17)
    blanket.add_element("Pb", 0.83)

    divertor = openmc_module.Material(name="divertor")
    divertor.set_density("g/cm3", 19.25)
    divertor.add_element("W", 1.0)

    vessel = openmc_module.Material(name="vacuum_vessel")
    vessel.set_density("g/cm3", 7.9)
    vessel.add_element("Fe", 0.70)
    vessel.add_element("Cr", 0.20)
    vessel.add_element("Ni", 0.10)

    shield = openmc_module.Material(name="shield")
    shield.set_density("g/cm3", 7.9)
    shield.add_element("Fe", 0.9)
    shield.add_element("C", 0.1)

    return {
        "blanket": blanket,
        "divertor": divertor,
        "vacuum_vessel": vessel,
        "shield": shield,
    }
