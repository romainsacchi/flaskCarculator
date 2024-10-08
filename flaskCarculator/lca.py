import numpy as np
from carculator import CarInputParameters, CarModel, fill_xarray_from_input_parameters, InventoryCar
from carculator_truck import TruckInputParameters, TruckModel, InventoryTruck
from carculator_bus import BusInputParameters, BusModel, InventoryBus
from carculator_two_wheeler import TwoWheelerInputParameters, TwoWheelerModel, InventoryTwoWheeler

from .data.mapping import FUEL_SPECS
from .output_validation import validate_output_data

models = {
    "car": {
        "model": CarModel,
        "inventory": InventoryCar,
        "input_parameters": CarInputParameters
    },
    "truck": {
        "model": TruckModel,
        "inventory": InventoryTruck,
        "input_parameters": TruckInputParameters
    },
    "bus": {
        "model": BusModel,
        "inventory": InventoryBus,
        "input_parameters": BusInputParameters
    },
    "two_wheeler": {
        "model": TwoWheelerModel,
        "inventory": InventoryTwoWheeler,
        "input_parameters": TwoWheelerInputParameters
    }
}


def set_combustion_power_share(array, params):
    """
    Sets the combustion power share in the array based on the powertrain type.
    """
    if params["powertrain"] in ["HEV-d", "HEV-p"]:
        array.loc[dict(parameter="combustion power share")] = params["primary_engine_power"] / params["total_engine_power"]
    elif params["powertrain"] in ["ICEV-d", "ICEV-p", "ICEV-g"]:
        array.loc[dict(parameter="combustion power share")] = 1
    elif params["powertrain"] in ["BEV", "FCEV"]:
        array.loc[dict(parameter="combustion power share")] = 0

    return array


def set_vehicle_properties_before_run(model, params):
    """
    Sets various properties of the vehicle model based on the provided parameters.
    """
    if params.get("fuel tank volume", 0) > 0:
        fuel_density = FUEL_SPECS[params["powertrain"]]["density"]
        model.array.loc[dict(parameter="fuel mass")] = params["fuel tank volume"] * fuel_density

    return model


def set_vehicle_properties_after_run(model, params):
    """
    Sets various properties of the vehicle model based on the provided parameters.
    """

    if params.get("driving mass", 0) > 0:
        model.array.loc[dict(parameter="driving mass")] = params["driving mass"]
    if params.get("TtW energy", 0) > 0:
        model.array.loc[dict(parameter="TtW energy")] = params["TtW energy"]
    if params.get("fuel consumption", 0) > 0:
        model.array.loc[dict(parameter="fuel consumption")] = params["fuel consumption"] / 100
    if params.get("electricity consumption", 0) > 0:
        model.array.loc[dict(parameter="electricity consumption")] = params["electricity consumption"] / 100

    if params.get("range", 0) > 0:
        model.array.loc[dict(parameter="range")] = params["range"]

    return model

def set_properties_for_plugin(model, params):
    """
    Sets various properties of the vehicle model based on the provided parameters.
    :param model:
    :param params:
    :return:
    """
    model.array.loc[dict(powertrain=params["powertrain"], parameter="electricity consumption")] = params["electricity consumption"] / 100
    model.array.loc[dict(powertrain=params["powertrain"], parameter="fuel consumption")] = params["fuel consumption"] / 100
    model.array.loc[dict(powertrain=params["powertrain"], parameter="TtW energy")] = params["TtW energy"]
    model.array.loc[dict(powertrain=params["powertrain"], parameter="electric energy stored")] = params["electric energy stored"]
    model.array.loc[dict(powertrain=params["powertrain"], parameter="glider base mass")] += (params["curb mass"] - model.array.loc[dict(powertrain=params["powertrain"], parameter="curb mass")])

    model.array.loc[dict(powertrain=params["powertrain"], parameter="combustion power")] = params["primary power"]
    model.array.loc[dict(powertrain=params["powertrain"], parameter="electric power")] = params["power"] - params["primary power"]
    model.array.loc[dict(powertrain=params["powertrain"], parameter="power")] = params["power"]
    model.set_vehicle_mass()
    model.set_component_masses()
    model["driving mass"] = params["driving mass"]

    range_c, range_km = 0, 0
    if params["powertrain"] == "PHEV-p":
        range_c = model.array.loc[dict(powertrain="PHEV-c-p", parameter="range")]
        range_km = model.array.loc[dict(powertrain="PHEV-p", parameter="range")]
    if params["powertrain"] == "PHEV-d":
        range_c = model.array.loc[dict(powertrain="PHEV-c-d", parameter="range")]
        range_km = model.array.loc[dict(powertrain="PHEV-d", parameter="range")]
    ratio_range = range_c / range_km
    model.array.loc[dict(powertrain=params["powertrain"], parameter="fuel mass")] /= ratio_range

    return model

def initialize_model(params, country="CH"):
    """
    Initializes and returns a CarModel instance with the given parameters.
    """

    input_parameters = models[params["vehicle_type"]]["input_parameters"]

    ip = input_parameters()
    ip.static()

    _, array = fill_xarray_from_input_parameters(
        ip,
        scope={"powertrain": [params["powertrain"]], "size": [params["size"]]}
    )
    array = array.interp(year=[params["year"]], kwargs={'fill_value': 'extrapolate'})
    array = set_combustion_power_share(array, params)

    model = models[params["vehicle_type"]]["model"]

    energy_storage = None
    if params.get("electric energy stored", 0) > 0:
        energy_storage = {
            "capacity": {
                (params["powertrain"], params["size"], params["year"]): params["electric energy stored"]
            },
        }

    if params.get("battery technology", None):
        if energy_storage is None:
            energy_storage = {}
        energy_storage["electric"] = {
            (params["powertrain"], params["size"], params["year"]): params["battery technology"]
        }

    power = None

    if params.get("power", 0) > 0:
        power = {
            (params["powertrain"], params["size"], params["year"]): params["power"]
        }

    target_mass = None
    if params.get("curb mass", 0) > 0:
        target_mass = {
            (params["powertrain"], params["size"], params["year"]): params["curb mass"]
        }

    energy_consumption = None
    if params.get("TtW energy", 0) > 0:
        energy_consumption = {
            (params["powertrain"], params["size"], params["year"]): params["TtW energy"]
        }

    m = model(
        array,
        country=country,
        cycle='WLTC',
        energy_storage=energy_storage,
        power=power,
        target_mass=target_mass,
        energy_consumption=energy_consumption,
        drop_hybrids=False
    )

    m = set_vehicle_properties_before_run(m, params)

    m.set_all()

    m = set_vehicle_properties_after_run(m, params)

    if params["powertrain"] in ["PHEV-d", "PHEV-p"]:
        m = set_properties_for_plugin(m, params)

    if params["vehicle_type"] == "car":
        m.drop_hybrid()

    errors = validate_output_data(data=m, request=params)

    if errors:
        raise ValueError(f"Validation failed: {errors}")

    inventory = models[params["vehicle_type"]]["inventory"]
    inventory = inventory(m)
    results = inventory.calculate_impacts()
    m.results = results.sel(value=0)

    return m
