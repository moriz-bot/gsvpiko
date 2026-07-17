"""Sensor preset for K3D40 serial number 24200767."""

SENSOR = {
    # 1. Identity
    "serial_number": "24200767",
    "model_name": "K3D40 10N",
    "sensor_type": "force_3d",

    # 2. Measurement and calibration
    "channel_count": 3,
    "axis_labels": ["x", "y", "z"],  # list[str | None], length = channel_count; used for channel names such as F1x, F1y, F1z.
    "quantity_types": ["force", "force", "force"],  # list[str], length = channel_count; examples: "force", "torque".
    "unit_codes": [3, 3, 3],  # list[int | None], length = channel_count; 3 = Newton in constants_units.py.

    # scaling_factors are GSVpiko scaling_factor values written per channel.
    # Form: list[float | None], length = channel_count.
    # Check relation: physical_full_scale / rated_outputs_mv_per_v * sensor_input_sensitivity_mv_per_v.
    "scaling_factors": [58.9213, 57.3874, 56.3868],

    "physical_full_scale": 10,  # float | None; rated physical full-scale value in the unit defined by unit_codes, here 10 N.
    "rated_outputs_mv_per_v": [0.594013, 0.60989, 0.6207125],  # list[float | None], length = channel_count; rated sensor output at physical_full_scale in mV/V.

    # calibration_matrix is the manufacturer calibration matrix.
    # Form: list[list[float]] | None, shape = channel_count x channel_count.
    # It maps sensor output in mV/V to the physical unit defined by unit_codes.
    # Example: [[16.0, 0.10, -0.10], [0.05, 16.2, 0.08], [0.20, -0.04, 15.9]].
    "calibration_matrix": [
        [16.8346483999508, 0.0525771580097326, -0.140442734133353],
        [0.0241052994802782, 16.3963993507026, -0.0546891334102286],
        [0.336859367757324, 0.0335119907574626, 16.1105181545401],
    ],

    # crosstalk_compensation_matrix is applied after diagonal scaling_factor conversion.
    # Form: list[list[float]] | None, shape = channel_count x channel_count.
    # Example form: [[1.0, 0.00617, -0.00629], [0.00313, 1.0, 0.00503], [0.0125, -0.00247, 1.0]].
    # It can be derived from calibration_matrix by dividing each matrix column by its diagonal element.
    "crosstalk_compensation_matrix": [
        [1.0, 0.00320662828985558, -0.00871745606107488],
        [0.00143188612601785, 1.0, -0.00339462287218965],
        [0.0200098843619632, 0.00204386280430688, 1.0],
    ],

    "calibration_reference": '20580450',  # str | None; calibration mark, certificate number, order number, or internal reference identifier.
    "calibration_date": '2025-01-16',  # str | None; ISO date "YYYY-MM-DD".

    # 3. Electrical compatibility / validation
    "sensor_input_mode": "bridge_5v",  # str | int | None; accepted names are defined in constants_sensor_input_modes.py.
    "sensor_input_sensitivity_mv_per_v": 3.5,  # float | None; effective input sensitivity that belongs to sensor_input_mode.
    "bridge_resistance_ohm": 350,  # float | None; nominal bridge resistance per axis.

    # 4. Recommended defaults
    "default_sample_rate_hz": None,  # float | None; setup-level values override this default.
    "default_analog_filter_hz": "low",  # str | int | None; "low"/28, "medium"/850/885, "high"/11400/11700.
    "default_digital_filter": None,  # dict | None; reserved for explicit digital-filter settings.
    "default_datatype": None,  # str | int | None; supported: "float32", "int24", "int16".
}
