#!/usr/bin/python3
# SPDX-License-Identifier: MIT
from pyudev import Context


def _get_property(prop, key, fallback="") -> str:
    """Get the property from the given key"""
    try:
        return prop.get(key, fallback)
    except UnicodeDecodeError:
        return ""


class Batteries:
    def __init__(self) -> None:
        self.pyudev = Context()

    def _get_battery(self, name) -> object:
        """Get the battery device object for the given name"""
        for dev in self.pyudev.list_devices(
            subsystem="power_supply", POWER_SUPPLY_TYPE="Battery"
        ):
            if not "PNP0C0A" in dev.device_path:
                continue
            desc = _get_property(dev.properties, "POWER_SUPPLY_NAME", "Unknown")
            if desc != name:
                continue
            return dev
        return None

    def get_batteries(self) -> list:
        """Get a list of battery names on the system"""
        names = []
        for dev in self.pyudev.list_devices(
            subsystem="power_supply", POWER_SUPPLY_TYPE="Battery"
        ):
            if not "PNP0C0A" in dev.device_path:
                continue
            names.append(_get_property(dev.properties, "POWER_SUPPLY_NAME", "Unknown"))
        return names

    def get_energy_unit(self, name) -> str:
        """Get the energy unit for the given battery name"""
        dev = self._get_battery(name)
        if not dev:
            return ""
        energy = _get_property(dev.properties, "POWER_SUPPLY_ENERGY_NOW")
        if energy:
            return "µWh"
        return "µAh"

    def get_energy(self, name) -> int:
        """Get the current energy for the given battery name"""
        dev = self._get_battery(name)
        if not dev:
            return ""
        energy = _get_property(dev.properties, "POWER_SUPPLY_ENERGY_NOW")
        if not energy:
            energy = _get_property(dev.properties, "POWER_SUPPLY_CHARGE_NOW")
        return energy

    def get_energy_full(self, name) -> int:
        """Get the energy when full for the given battery name"""
        dev = self._get_battery(name)
        if not dev:
            return ""
        energy = _get_property(dev.properties, "POWER_SUPPLY_ENERGY_FULL")
        if not energy:
            energy = _get_property(dev.properties, "POWER_SUPPLY_CHARGE_FULL")
        return energy

    def get_description_string(self, name) -> str:
        """Get a description string for the given battery name"""
        dev = self._get_battery(name)
        if not dev:
            return ""
        man = _get_property(dev.properties, "POWER_SUPPLY_MANUFACTURER", "")
        model = _get_property(dev.properties, "POWER_SUPPLY_MODEL_NAME", "")
        full = self.get_energy_full(name)
        full_design = _get_property(dev.properties, "POWER_SUPPLY_ENERGY_FULL_DESIGN")
        if not full_design:
            full_design = _get_property(
                dev.properties, "POWER_SUPPLY_CHARGE_FULL_DESIGN"
            )

        percent = float(full) / int(full_design)
        return f"Battery {name} ({man} {model}) is operating at {percent:.2%} of design"
