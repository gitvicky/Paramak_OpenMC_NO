from __future__ import annotations

from typing import Dict


def build_materials(openmc_module) -> Dict[str, object]:
    """Create a conservative default material map keyed by DAGMC tags."""

    vacuum = openmc_module.Material(name="vacuum")
    vacuum.set_density("g/cm3", 1.0e-12)
    vacuum.add_element("H", 1.0)

    vacuum_comp = openmc_module.Material(name="vacuum_comp")
    vacuum_comp.set_density("g/cm3", 1.0e-12)
    vacuum_comp.add_element("H", 1.0)

    blanket = openmc_module.Material(name="blanket")
    blanket.set_density("g/cm3", 10.0)
    blanket.add_element("Li", 0.17)
    blanket.add_element("Pb", 0.83)

    first_wall = openmc_module.Material(name="first_wall")
    first_wall.set_density("g/cm3", 7.9)
    first_wall.add_element("Fe", 0.70)
    first_wall.add_element("Cr", 0.20)
    first_wall.add_element("Ni", 0.10)

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
        "vacuum": vacuum,
        "vacuum_comp": vacuum_comp,
        "blanket": blanket,
        "first_wall": first_wall,
        "vacuum_vessel": vessel,
        "shield": shield,
    }
