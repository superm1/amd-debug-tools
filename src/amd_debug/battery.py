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

    def _get_design_voltage(self, dev) -> str:
        """Get the design voltage in µV for the given battery"""
        for key in [
            "POWER_SUPPLY_VOLTAGE_MAX_DESIGN",
            "POWER_SUPPLY_VOLTAGE_MIN_DESIGN",
            "POWER_SUPPLY_VOLTAGE_NOW",
        ]:
            voltage = _get_property(dev.properties, key)
            if voltage:
                return voltage
        return ""

    def _charge_to_energy(self, dev, charge):
        """Convert battery charge in µAh to energy in µWh"""
        voltage = self._get_design_voltage(dev)
        if not charge or not voltage:
            return ""
        return str(round(int(charge) * int(voltage) / 1000000))

    def get_energy(self, name) -> int:
        """Get the current energy for the given battery name"""
        dev = self._get_battery(name)
        if not dev:
            return ""
        energy = _get_property(dev.properties, "POWER_SUPPLY_ENERGY_NOW")
        if not energy:
            charge = _get_property(dev.properties, "POWER_SUPPLY_CHARGE_NOW")
            energy = self._charge_to_energy(dev, charge)
        return energy

    def get_energy_full(self, name) -> int:
        """Get the energy when full for the given battery name"""
        dev = self._get_battery(name)
        if not dev:
            return ""
        energy = _get_property(dev.properties, "POWER_SUPPLY_ENERGY_FULL")
        if not energy:
            charge = _get_property(dev.properties, "POWER_SUPPLY_CHARGE_FULL")
            energy = self._charge_to_energy(dev, charge)
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
            charge_full_design = _get_property(
                dev.properties, "POWER_SUPPLY_CHARGE_FULL_DESIGN"
            )
            full_design = self._charge_to_energy(dev, charge_full_design)

        percent = float(full) / int(full_design)
        return f"Battery {name} ({man} {model}) is operating at {percent:.2%} of design"
