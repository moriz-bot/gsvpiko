"""Resolve and validate sensor calibration data used by setup validation.

The functions in this module operate on sensor preset dictionaries. They do not
communicate with GSV hardware and they do not calculate new calibration data.
They only derive and verify values that follow from already known calibration
sheet numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Any, Sequence

from ..constants import constants_sensor_input_modes as SENSOR_INPUT_MODE

FLOAT_REL_TOL = 1e-4
FLOAT_ABS_TOL = 1e-3
MATRIX_REL_TOL = 1e-4
MATRIX_ABS_TOL = 1e-6


@dataclass(frozen=True)
class SensorValidationIssue:
    """One sensor-validation issue with a compact key and readable message."""

    key: str
    message: str


@dataclass(frozen=True)
class SensorValidationReport:
    """Resolved sensor preset plus collected validation messages."""

    sensor_config: dict[str, Any]
    errors: list[SensorValidationIssue] = field(default_factory=list)
    warnings: list[SensorValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return whether no validation errors were collected."""
        return not self.errors


def resolve_sensor_config(
    sensor_config: dict[str, Any],
) -> SensorValidationReport:
    """Return a sensor config copy with derived calibration fields filled in.

    Resolution rule for derived values:
    - if a configured value and a calculated value both exist, they must match;
    - if the configured value is missing, the calculated value is used;
    - if no value can be configured or calculated, validation reports an error.
    """
    resolved = dict(sensor_config)
    errors: list[SensorValidationIssue] = []
    warnings: list[SensorValidationIssue] = []

    channel_count = _read_channel_count(sensor_config, errors)
    if channel_count is None:
        return SensorValidationReport(resolved, errors, warnings)

    sensor_input_mode, sensor_input_sensitivity = _resolve_input_mode_and_sensitivity(
        sensor_config,
        errors,
    )

    scaling_factors_config = _numeric_sequence_or_none(
        sensor_config.get("scaling_factors"),
        length=channel_count,
        field_name="scaling_factors",
        errors=errors,
        allow_none_items=True,
    )
    physical_full_scale = _float_or_none(
        sensor_config.get("physical_full_scale"),
        field_name="physical_full_scale",
        errors=errors,
    )
    rated_outputs_mv_per_v = _numeric_sequence_or_none(
        sensor_config.get("rated_outputs_mv_per_v"),
        length=channel_count,
        field_name="rated_outputs_mv_per_v",
        errors=errors,
        allow_none_items=True,
    )
    calibration_matrix = _matrix_or_none(
        sensor_config.get("calibration_matrix"),
        size=channel_count,
        field_name="calibration_matrix",
        errors=errors,
    )
    crosstalk_compensation_matrix_config = _matrix_or_none(
        sensor_config.get("crosstalk_compensation_matrix"),
        size=channel_count,
        field_name="crosstalk_compensation_matrix",
        errors=errors,
    )

    resolved["physical_full_scale"] = physical_full_scale
    resolved["rated_outputs_mv_per_v"] = rated_outputs_mv_per_v
    resolved["calibration_matrix"] = calibration_matrix

    calibration_diagonal_from_rated_outputs = _calculate_calibration_diagonal_from_rated_outputs(
        physical_full_scale=physical_full_scale,
        rated_outputs_mv_per_v=rated_outputs_mv_per_v,
        errors=errors,
    )
    calibration_diagonal_from_matrix = _diagonal_from_matrix(
        calibration_matrix,
        errors=errors,
        field_name="calibration_matrix",
    )

    if (
        calibration_diagonal_from_rated_outputs is not None
        and calibration_diagonal_from_matrix is not None
    ):
        _compare_float_sequences(
            configured=calibration_diagonal_from_matrix,
            calculated=calibration_diagonal_from_rated_outputs,
            configured_field_name="calibration_matrix diagonal",
            calculated_field_name="physical_full_scale / rated_outputs_mv_per_v",
            errors=errors,
        )

    calibration_diagonal = _select_calibration_diagonal(
        calibration_diagonal_from_matrix=calibration_diagonal_from_matrix,
        calibration_diagonal_from_rated_outputs=calibration_diagonal_from_rated_outputs,
    )

    if sensor_input_sensitivity is None and _is_complete_sequence(scaling_factors_config):
        sensor_input_sensitivity = _derive_input_sensitivity_from_scaling_factors(
            scaling_factors=scaling_factors_config,
            calibration_diagonal=calibration_diagonal,
            errors=errors,
        )
        if sensor_input_mode is None and sensor_input_sensitivity is not None:
            sensor_input_mode = _infer_mode_from_sensitivity(sensor_input_sensitivity, errors)

    if calibration_diagonal is None and _is_complete_sequence(scaling_factors_config):
        calibration_diagonal = _derive_calibration_diagonal_from_scaling_factors(
            scaling_factors=scaling_factors_config,
            sensor_input_sensitivity_mv_per_v=sensor_input_sensitivity,
            errors=errors,
        )

    _validate_scaling_information(
        scaling_factors_config=scaling_factors_config,
        physical_full_scale=physical_full_scale,
        rated_outputs_mv_per_v=rated_outputs_mv_per_v,
        sensor_input_sensitivity_mv_per_v=sensor_input_sensitivity,
        calibration_matrix=calibration_matrix,
        errors=errors,
    )

    resolved["sensor_input_mode"] = sensor_input_mode
    resolved["sensor_input_sensitivity_mv_per_v"] = sensor_input_sensitivity

    scaling_factors_calc = _select_scaling_factors_calc(
        sensor_input_sensitivity_mv_per_v=sensor_input_sensitivity,
        calibration_diagonal_from_matrix=calibration_diagonal_from_matrix,
        calibration_diagonal_from_rated_outputs=calibration_diagonal_from_rated_outputs,
        calibration_diagonal_fallback=calibration_diagonal,
    )
    scaling_factors = _resolve_scaling_factors(
        scaling_factors_config=scaling_factors_config,
        scaling_factors_calc=scaling_factors_calc,
        channel_count=channel_count,
        errors=errors,
    )
    resolved["scaling_factors"] = scaling_factors

    crosstalk_compensation_matrix_calc = None
    if calibration_matrix is not None and calibration_diagonal_from_matrix is not None:
        crosstalk_compensation_matrix_calc = calculate_crosstalk_compensation_matrix(
            calibration_matrix,
            calibration_diagonal_from_matrix,
        )

    resolved["crosstalk_compensation_matrix"] = _resolve_crosstalk_compensation_matrix(
        crosstalk_compensation_matrix_config=crosstalk_compensation_matrix_config,
        crosstalk_compensation_matrix_calc=crosstalk_compensation_matrix_calc,
        errors=errors,
    )

    return SensorValidationReport(resolved, errors, warnings)

def calculate_crosstalk_compensation_matrix(
    calibration_matrix: Sequence[Sequence[float]],
    calibration_diagonal: Sequence[float] | None = None,
) -> list[list[float]]:
    """Divide each calibration-matrix column by its main-diagonal element."""
    diagonal = list(calibration_diagonal or [
        float(row[index])
        for index, row in enumerate(calibration_matrix)
    ])
    if any(value == 0 for value in diagonal):
        raise ValueError("calibration_matrix diagonal must not contain zero.")

    return [
        [float(value) / diagonal[column_index] for column_index, value in enumerate(row)]
        for row in calibration_matrix
    ]


def _read_channel_count(
    sensor_config: dict[str, Any],
    errors: list[SensorValidationIssue],
) -> int | None:
    """Return channel_count if it can be interpreted."""
    try:
        channel_count = int(sensor_config.get("channel_count"))
    except Exception as error:
        errors.append(
            SensorValidationIssue(
                key="invalid_channel_count",
                message=f"Sensor channel_count is invalid: {error}",
            )
        )
        return None

    if channel_count <= 0:
        errors.append(
            SensorValidationIssue(
                key="invalid_channel_count",
                message="Sensor channel_count must be positive.",
            )
        )
        return None

    return channel_count


def _resolve_input_mode_and_sensitivity(
    sensor_config: dict[str, Any],
    errors: list[SensorValidationIssue],
) -> tuple[int | None, float | None]:
    """Resolve sensor input mode and its linked input sensitivity."""
    mode_config = sensor_config.get("sensor_input_mode")
    sensitivity_config = _float_or_none(
        sensor_config.get("sensor_input_sensitivity_mv_per_v"),
        field_name="sensor_input_sensitivity_mv_per_v",
        errors=errors,
    )

    mode = None
    if mode_config is not None:
        try:
            mode = SENSOR_INPUT_MODE.normalize_sensor_input_mode(mode_config)
        except Exception as error:
            errors.append(
                SensorValidationIssue(
                    key="invalid_sensor_input_mode",
                    message=str(error),
                )
            )
            return None, sensitivity_config

    if mode is None and sensitivity_config is not None:
        mode = _infer_mode_from_sensitivity(sensitivity_config, errors)

    implied_sensitivity = SENSOR_INPUT_MODE.get_input_sensitivity_mv_per_v(mode)
    if sensitivity_config is None:
        return mode, implied_sensitivity

    if implied_sensitivity is not None and not isclose(
        sensitivity_config,
        float(implied_sensitivity),
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        errors.append(
            SensorValidationIssue(
                key="sensor_input_sensitivity_mismatch",
                message=(
                    "sensor_input_mode and sensor_input_sensitivity_mv_per_v "
                    f"do not match: mode implies {implied_sensitivity}, "
                    f"configured {sensitivity_config}."
                ),
            )
        )

    return mode, sensitivity_config


def _infer_mode_from_sensitivity(
    sensitivity_mv_per_v: float,
    errors: list[SensorValidationIssue],
) -> int | None:
    """Infer a unique bridge input mode from its input sensitivity."""
    matches = []
    for mode, definition in SENSOR_INPUT_MODE.MODE_DEFINITIONS.items():
        mode_sensitivity = definition.get("input_sensitivity_mv_per_v")
        if mode_sensitivity is None:
            continue
        if isclose(
            float(mode_sensitivity),
            float(sensitivity_mv_per_v),
            rel_tol=FLOAT_REL_TOL,
            abs_tol=FLOAT_ABS_TOL,
        ):
            matches.append(mode)

    if len(matches) == 1:
        return matches[0]

    errors.append(
        SensorValidationIssue(
            key="sensor_input_mode_not_inferable",
            message=(
                "sensor_input_mode is missing and cannot be inferred uniquely "
                f"from sensor_input_sensitivity_mv_per_v={sensitivity_mv_per_v}."
            ),
        )
    )
    return None


def _calculate_calibration_diagonal_from_rated_outputs(
    *,
    physical_full_scale: float | None,
    rated_outputs_mv_per_v: Sequence[float | None] | None,
    errors: list[SensorValidationIssue],
) -> list[float] | None:
    """Calculate the diagonal sensitivity from rated outputs if possible."""
    if physical_full_scale is None or rated_outputs_mv_per_v is None:
        return None
    if any(value is None for value in rated_outputs_mv_per_v):
        return None

    diagonal = []
    for index, rated_output in enumerate(rated_outputs_mv_per_v):
        assert rated_output is not None
        if rated_output == 0:
            errors.append(
                SensorValidationIssue(
                    key="invalid_rated_output",
                    message=(
                        "rated_outputs_mv_per_v must not contain zero "
                        f"at index {index}."
                    ),
                )
            )
            return None
        diagonal.append(float(physical_full_scale) / float(rated_output))
    return diagonal


def _select_calibration_diagonal(
    *,
    calibration_diagonal_from_matrix: Sequence[float] | None,
    calibration_diagonal_from_rated_outputs: Sequence[float] | None,
) -> list[float] | None:
    """Return the preferred diagonal sensitivity source if available."""
    source = (
        calibration_diagonal_from_matrix
        if calibration_diagonal_from_matrix is not None
        else calibration_diagonal_from_rated_outputs
    )
    if source is None:
        return None
    return [float(value) for value in source]


def _is_complete_sequence(values: Sequence[float | None] | None) -> bool:
    """Return whether a sequence exists and contains no None entries."""
    return values is not None and all(value is not None for value in values)


def _derive_input_sensitivity_from_scaling_factors(
    *,
    scaling_factors: Sequence[float | None],
    calibration_diagonal: Sequence[float] | None,
    errors: list[SensorValidationIssue],
) -> float | None:
    """Derive input sensitivity from scaling_factors and a calibration diagonal."""
    if calibration_diagonal is None:
        return None

    calculated_values = []
    for index, scaling_factor in enumerate(scaling_factors):
        if scaling_factor is None:
            return None
        diagonal_value = float(calibration_diagonal[index])
        if diagonal_value == 0:
            return None
        calculated_values.append(float(scaling_factor) / diagonal_value)

    first_value = calculated_values[0]
    for index, value in enumerate(calculated_values[1:], start=1):
        if not isclose(value, first_value, rel_tol=FLOAT_REL_TOL, abs_tol=FLOAT_ABS_TOL):
            errors.append(
                SensorValidationIssue(
                    key="sensor_input_sensitivity_not_consistent",
                    message=(
                        "sensor_input_sensitivity_mv_per_v cannot be derived "
                        "consistently from scaling_factors and calibration data: "
                        f"index 0 gives {first_value}, index {index} gives {value}."
                    ),
                )
            )
            return None
    return first_value


def _derive_calibration_diagonal_from_scaling_factors(
    *,
    scaling_factors: Sequence[float | None],
    sensor_input_sensitivity_mv_per_v: float | None,
    errors: list[SensorValidationIssue],
) -> list[float] | None:
    """Derive diagonal sensitivity from scaling_factors and input sensitivity."""
    if sensor_input_sensitivity_mv_per_v is None:
        return None
    if sensor_input_sensitivity_mv_per_v == 0:
        errors.append(
            SensorValidationIssue(
                key="invalid_sensor_input_sensitivity",
                message="sensor_input_sensitivity_mv_per_v must not be zero.",
            )
        )
        return None
    if any(value is None for value in scaling_factors):
        return None
    return [float(value) / float(sensor_input_sensitivity_mv_per_v) for value in scaling_factors]


def _validate_scaling_information(
    *,
    scaling_factors_config: Sequence[float | None] | None,
    physical_full_scale: float | None,
    rated_outputs_mv_per_v: Sequence[float | None] | None,
    sensor_input_sensitivity_mv_per_v: float | None,
    calibration_matrix: Sequence[Sequence[float]] | None,
    errors: list[SensorValidationIssue],
) -> None:
    """Require enough information to validate or derive scaling_factors."""
    scaling_factors_known = _is_complete_sequence(scaling_factors_config)
    physical_full_scale_known = physical_full_scale is not None
    rated_outputs_known = _is_complete_sequence(rated_outputs_mv_per_v)
    input_sensitivity_known = sensor_input_sensitivity_mv_per_v is not None
    calibration_matrix_known = calibration_matrix is not None

    if calibration_matrix_known:
        if input_sensitivity_known or scaling_factors_known:
            return
        errors.append(
            SensorValidationIssue(
                key="insufficient_scaling_information",
                message=(
                    "Sensor preset cannot validate or derive scaling_factors. "
                    "calibration_matrix requires sensor_input_mode/"
                    "sensor_input_sensitivity_mv_per_v, or configured scaling_factors "
                    "from which input sensitivity can be derived."
                ),
            )
        )
        return

    known_count = sum(
        1
        for known in (
            scaling_factors_known,
            physical_full_scale_known,
            rated_outputs_known,
            input_sensitivity_known,
        )
        if known
    )
    if known_count >= 3:
        return

    errors.append(
        SensorValidationIssue(
            key="insufficient_scaling_information",
            message=(
                "Sensor preset cannot validate or derive scaling_factors. "
                "Provide at least three of these information groups: "
                "scaling_factors, physical_full_scale, rated_outputs_mv_per_v, "
                "sensor_input_mode/sensor_input_sensitivity_mv_per_v. "
                "Alternatively provide calibration_matrix with sensor_input_mode/"
                "sensor_input_sensitivity_mv_per_v."
            ),
        )
    )


def _select_scaling_factors_calc(
    *,
    sensor_input_sensitivity_mv_per_v: float | None,
    calibration_diagonal_from_matrix: Sequence[float] | None,
    calibration_diagonal_from_rated_outputs: Sequence[float] | None,
    calibration_diagonal_fallback: Sequence[float] | None = None,
) -> list[float] | None:
    """Return calculated scaling factors from the best available source."""
    if sensor_input_sensitivity_mv_per_v is None:
        return None

    calibration_diagonal = (
        calibration_diagonal_from_matrix
        if calibration_diagonal_from_matrix is not None
        else calibration_diagonal_from_rated_outputs
    )
    if calibration_diagonal is None:
        calibration_diagonal = calibration_diagonal_fallback
    if calibration_diagonal is None:
        return None

    return [
        float(sensor_input_sensitivity_mv_per_v) * float(value)
        for value in calibration_diagonal
    ]


def _resolve_scaling_factors(
    *,
    scaling_factors_config: Sequence[float | None] | None,
    scaling_factors_calc: Sequence[float] | None,
    channel_count: int,
    errors: list[SensorValidationIssue],
) -> list[float | None]:
    """Return configured or calculated scaling factors after consistency checks."""
    if scaling_factors_config is not None and scaling_factors_calc is not None:
        _compare_float_sequences(
            configured=scaling_factors_config,
            calculated=scaling_factors_calc,
            configured_field_name="scaling_factors",
            calculated_field_name="calculated scaling_factors",
            errors=errors,
        )

    if scaling_factors_config is not None and all(
        value is not None
        for value in scaling_factors_config
    ):
        return list(scaling_factors_config)

    if scaling_factors_calc is not None:
        return list(scaling_factors_calc)

    errors.append(
        SensorValidationIssue(
            key="missing_scaling_factors",
            message=(
                "Sensor preset cannot resolve scaling_factors. Configure "
                "scaling_factors directly or provide physical_full_scale, "
                "rated_outputs_mv_per_v, and sensor input sensitivity."
            ),
        )
    )
    if scaling_factors_config is not None:
        return list(scaling_factors_config)
    return [None for _ in range(channel_count)]


def _resolve_crosstalk_compensation_matrix(
    *,
    crosstalk_compensation_matrix_config: Sequence[Sequence[float]] | None,
    crosstalk_compensation_matrix_calc: Sequence[Sequence[float]] | None,
    errors: list[SensorValidationIssue],
) -> list[list[float]] | None:
    """Return configured or calculated crosstalk compensation matrix."""
    if (
        crosstalk_compensation_matrix_config is not None
        and crosstalk_compensation_matrix_calc is not None
    ):
        _compare_float_matrices(
            configured=crosstalk_compensation_matrix_config,
            calculated=crosstalk_compensation_matrix_calc,
            configured_field_name="crosstalk_compensation_matrix",
            calculated_field_name="calculated crosstalk_compensation_matrix",
            errors=errors,
        )

    if crosstalk_compensation_matrix_config is not None:
        return [list(row) for row in crosstalk_compensation_matrix_config]
    if crosstalk_compensation_matrix_calc is not None:
        return [list(row) for row in crosstalk_compensation_matrix_calc]
    return None


def _diagonal_from_matrix(
    matrix: Sequence[Sequence[float]] | None,
    *,
    errors: list[SensorValidationIssue],
    field_name: str,
) -> list[float] | None:
    """Return the main diagonal of a square matrix."""
    if matrix is None:
        return None

    diagonal = [float(row[index]) for index, row in enumerate(matrix)]
    for index, value in enumerate(diagonal):
        if value == 0:
            errors.append(
                SensorValidationIssue(
                    key="invalid_calibration_matrix_diagonal",
                    message=f"{field_name} diagonal must not contain zero at index {index}.",
                )
            )
            return None
    return diagonal


def _numeric_sequence_or_none(
    value: Any,
    *,
    length: int,
    field_name: str,
    errors: list[SensorValidationIssue],
    allow_none_items: bool,
) -> list[float | None] | None:
    """Return one numeric list, None, or register validation errors."""
    if value is None:
        return None
    if not isinstance(value, list):
        errors.append(
            SensorValidationIssue(
                key="invalid_sequence",
                message=f"Sensor {field_name!r} must be a list.",
            )
        )
        return None
    if len(value) != length:
        errors.append(
            SensorValidationIssue(
                key="sequence_length_mismatch",
                message=(
                    f"Sensor {field_name!r} length mismatch: "
                    f"expected {length}, got {len(value)}."
                ),
            )
        )
        return None

    result: list[float | None] = []
    for index, item in enumerate(value):
        if item is None and allow_none_items:
            result.append(None)
            continue
        try:
            result.append(float(item))
        except Exception as error:
            errors.append(
                SensorValidationIssue(
                    key="invalid_numeric_value",
                    message=f"Sensor {field_name!r}[{index}] is invalid: {error}",
                )
            )
            return None
    return result


def _matrix_or_none(
    value: Any,
    *,
    size: int,
    field_name: str,
    errors: list[SensorValidationIssue],
) -> list[list[float]] | None:
    """Return one numeric square matrix, None, or register validation errors."""
    if value is None:
        return None
    if not isinstance(value, list):
        errors.append(
            SensorValidationIssue(
                key="invalid_matrix",
                message=f"Sensor {field_name!r} must be a list of rows.",
            )
        )
        return None
    if len(value) != size:
        errors.append(
            SensorValidationIssue(
                key="matrix_size_mismatch",
                message=f"Sensor {field_name!r} row count must be {size}, got {len(value)}.",
            )
        )
        return None

    matrix: list[list[float]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list):
            errors.append(
                SensorValidationIssue(
                    key="invalid_matrix_row",
                    message=f"Sensor {field_name!r}[{row_index}] must be a list.",
                )
            )
            return None
        if len(row) != size:
            errors.append(
                SensorValidationIssue(
                    key="matrix_size_mismatch",
                    message=(
                        f"Sensor {field_name!r}[{row_index}] length must be "
                        f"{size}, got {len(row)}."
                    ),
                )
            )
            return None
        try:
            matrix.append([float(item) for item in row])
        except Exception as error:
            errors.append(
                SensorValidationIssue(
                    key="invalid_matrix_value",
                    message=f"Sensor {field_name!r}[{row_index}] contains invalid value: {error}",
                )
            )
            return None
    return matrix


def _float_or_none(
    value: Any,
    *,
    field_name: str,
    errors: list[SensorValidationIssue],
) -> float | None:
    """Return a float for a configured scalar value."""
    if value is None:
        return None
    try:
        return float(value)
    except Exception as error:
        errors.append(
            SensorValidationIssue(
                key="invalid_numeric_value",
                message=f"Sensor {field_name!r} is invalid: {error}",
            )
        )
        return None


def _compare_float_sequences(
    *,
    configured: Sequence[float | None],
    calculated: Sequence[float],
    configured_field_name: str,
    calculated_field_name: str,
    errors: list[SensorValidationIssue],
) -> None:
    """Validate that two numeric sequences agree within rounding tolerance."""
    for index, configured_value in enumerate(configured):
        if configured_value is None:
            continue
        calculated_value = float(calculated[index])
        if not isclose(
            float(configured_value),
            calculated_value,
            rel_tol=FLOAT_REL_TOL,
            abs_tol=FLOAT_ABS_TOL,
        ):
            errors.append(
                SensorValidationIssue(
                    key="sensor_calibration_mismatch",
                    message=(
                        f"{configured_field_name}[{index}]={configured_value:g} "
                        f"does not match {calculated_field_name}[{index}]="
                        f"{calculated_value:g}."
                    ),
                )
            )


def _compare_float_matrices(
    *,
    configured: Sequence[Sequence[float]],
    calculated: Sequence[Sequence[float]],
    configured_field_name: str,
    calculated_field_name: str,
    errors: list[SensorValidationIssue],
) -> None:
    """Validate that two numeric matrices agree within rounding tolerance."""
    for row_index, row in enumerate(configured):
        for column_index, configured_value in enumerate(row):
            calculated_value = float(calculated[row_index][column_index])
            if not isclose(
                float(configured_value),
                calculated_value,
                rel_tol=MATRIX_REL_TOL,
                abs_tol=MATRIX_ABS_TOL,
            ):
                errors.append(
                    SensorValidationIssue(
                        key="sensor_matrix_mismatch",
                        message=(
                            f"{configured_field_name}[{row_index}][{column_index}]="
                            f"{configured_value:g} does not match "
                            f"{calculated_field_name}[{row_index}][{column_index}]="
                            f"{calculated_value:g}."
                        ),
                    )
                )
