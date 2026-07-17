"""Template sensor configurations for GSVpiko.

Resolution order:
1. setup value, if it is not None
2. sensor default, if it exists and is not None
3. device default, if it exists and is not None

The source configuration dictionaries are not modified. GSVpiko builds a
resolved runtime configuration before writing settings to the device.

A sensor preset describes identity, calibration, electrical compatibility, and
optional defaults. It does not describe where the sensor is connected. The setup
assigns sensors to GSV sockets.
"""

K3D40_FORCE_3D_TEMPLATE = {
    # serial_number is stored as a string because sensor serial numbers can
    # contain leading zeros or non-numeric characters.
    "serial_number": "00000000",
    "model_name": "K3D40",
    "sensor_type": "force_3d",

    # channel_count defines how many analogue GSV channels this sensor occupies.
    # The following lists must have exactly channel_count entries:
    # - axis_labels
    # - quantity_types
    # - unit_codes
    # - scaling_factors
    # - rated_outputs_mv_per_v
    "channel_count": 3,

    # axis_labels are used as suffixes for output column names.
    # Example for a force sensor with sensor index 1: F1x, F1y, F1z.
    # Use None for a 1D sensor if no axis suffix should be appended.
    "axis_labels": ["x", "y", "z"],

    # quantity_types choose the physical quantity symbol used for column names.
    # Examples: "force" -> F, "torque" -> M.
    "quantity_types": ["force", "force", "force"],

    # unit_codes follow the GSV unit constants. 3 = Newton.
    "unit_codes": [3, 3, 3],

    # scaling_factors are GSVpiko scaling_factor values written per channel.
    # GSVmulti uses the term UserScaling for the same device-side value.
    # Form: list[float | None], length = channel_count.
    # Check relation: physical_full_scale / rated_outputs_mv_per_v * sensor_input_sensitivity_mv_per_v.
    "scaling_factors": [None, None, None],

    # physical_full_scale is the rated physical full-scale value in the unit
    # defined by unit_codes, for example 10 N.
    "physical_full_scale": None,

    # rated_outputs_mv_per_v stores the rated sensor output at
    # physical_full_scale in mV/V, one value per channel.
    "rated_outputs_mv_per_v": [None, None, None],

    # calibration_matrix is the manufacturer calibration matrix.
    # Form: list[list[float]] | None, shape = channel_count x channel_count.
    # It maps sensor output in mV/V to the physical unit defined by unit_codes.
    # Example: [[16.0, 0.10, -0.10], [0.05, 16.2, 0.08], [0.20, -0.04, 15.9]].
    "calibration_matrix": None,

    # crosstalk_compensation_matrix is applied after diagonal scaling_factor conversion.
    # Form: list[list[float]] | None, shape = channel_count x channel_count.
    # Example form: [[1.0, 0.00617, -0.00629], [0.00313, 1.0, 0.00503], [0.0125, -0.00247, 1.0]].
    # It can be derived from calibration_matrix by dividing each matrix column by its diagonal element.
    "crosstalk_compensation_matrix": None,

    "calibration_reference": None,  # str | None; calibration mark, certificate number, order number, or internal reference identifier.
    "calibration_date": None,  # str | None; ISO date "YYYY-MM-DD".

    # sensor_input_mode defines the electrical input mode used by the GSV.
    # Accepted names are defined in constants_sensor_input_modes.py.
    "sensor_input_mode": "bridge_5v",

    # If this value is None, GSVpiko derives it from sensor_input_mode where
    # possible. If it is set, it must match the selected mode.
    "sensor_input_sensitivity_mv_per_v": 3.5,

    # bridge_resistance_ohm documents electrical compatibility of the bridge.
    # It is not a scaling factor.
    "bridge_resistance_ohm": 350,

    # sample_rate_hz is the requested GSV output sample/frame rate. Define it
    # in the setup when one sample rate applies to the whole measurement setup.
    "default_sample_rate_hz": None,

    # Analogue filter cutoff frequency:
    # "low" = 28 Hz, "medium" = 850/885 Hz, "high" = 11400/11700 Hz,
    # or an integer Hz value accepted by the device.
    "default_analog_filter_hz": None,

    # Datatypes are defined in constants_datatypes.SUPPORTED_DATATYPE_NAMES:
    # "float32" = largest frame, directly parsed as float values
    # "int24"   = smaller frame, raw integer values
    # "int16"   = smallest frame, raw integer values
    "default_datatype": None,

    "default_digital_filter": None,
}

BRIDGE_1D_FORCE_TEMPLATE = {
    "serial_number": "00000000",
    "model_name": "CUSTOM_1D_BRIDGE",
    "sensor_type": "force_1d",

    "channel_count": 1,
    "axis_labels": [None],
    "quantity_types": ["force"],
    "unit_codes": [3],
    "scaling_factors": [None],
    "physical_full_scale": None,
    "rated_outputs_mv_per_v": [None],
    "calibration_matrix": None,
    "crosstalk_compensation_matrix": None,
    "calibration_reference": None,
    "calibration_date": None,

    "sensor_input_mode": "bridge_5v",
    "sensor_input_sensitivity_mv_per_v": 3.5,
    "bridge_resistance_ohm": 350,

    "default_sample_rate_hz": None,
    "default_analog_filter_hz": None,
    "default_datatype": None,
    "default_digital_filter": None,
}

DIGITAL_INPUT_TEMPLATE = {
    # Digital sensors are represented in setup files but are not supported by
    # the analogue sensor setup application.
    "serial_number": "digital_input_0000",
    "model_name": "DIGITAL_INPUT",
    "sensor_type": "digital_input",
    "implemented": False,

    "channel_count": 1,
    "axis_labels": [None],
    "quantity_types": ["digital"],
    "unit_codes": [None],
    "scaling_factors": [None],
    "physical_full_scale": None,
    "rated_outputs_mv_per_v": [None],
    "calibration_matrix": None,
    "crosstalk_compensation_matrix": None,
    "calibration_reference": None,
    "calibration_date": None,

    "sensor_input_mode": None,
    "sensor_input_sensitivity_mv_per_v": None,
    "bridge_resistance_ohm": None,

    "default_sample_rate_hz": None,
    "default_analog_filter_hz": None,
    "default_datatype": None,
    "default_digital_filter": None,
}
