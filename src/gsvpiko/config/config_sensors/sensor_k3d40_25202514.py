"""Sensor preset for K3D40 serial number 25202514."""

SENSOR = {
    # 1. Identity
    "serial_number": "25202514",
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
    "scaling_factors": [57.833335, 58.665845, 59.094560],

    "physical_full_scale": 10,  # float | None; rated physical full-scale value in the unit defined by unit_codes, here 10 N.
    "rated_outputs_mv_per_v": [0.60518730, 0.59659926, 0.59227110],  # list[float | None], length = channel_count; rated sensor output at physical_full_scale in mV/V.

    # calibration_matrix is the manufacturer calibration matrix.
    # Form: list[list[float]] | None, shape = channel_count x channel_count.
    # It maps sensor output in mV/V to the physical unit defined by unit_codes.
    # Example: [[16.0, 0.10, -0.10], [0.05, 16.2, 0.08], [0.20, -0.04, 15.9]].
    "calibration_matrix": [
        [16.52381, 0.04877873, -0.210323],
        [0.0392913, 16.76167, -0.1123209],
        [0.4237677, 0.05495199, 16.88416],
    ],

    # crosstalk_compensation_matrix is applied after diagonal scaling_factor conversion.
    # Form: list[list[float]] | None, shape = channel_count x channel_count.
    # Example form: [[1.0, 0.00617, -0.00629], [0.00313, 1.0, 0.00503], [0.0125, -0.00247, 1.0]].
    # It can be derived from calibration_matrix by dividing each matrix column by its diagonal element.
    "crosstalk_compensation_matrix": [
        [1.0, 0.00291014, -0.01245682],
        [0.00237786, 1.0, -0.00665244],
        [0.02564588, 0.00327843, 1.0],
    ],

    "calibration_reference": "291411 ME 2026-04; order 20585670",  # str | None; calibration mark, certificate number, order number, or internal reference identifier.
    "calibration_date": "2026-04-28",  # str | None; ISO date "YYYY-MM-DD".

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
