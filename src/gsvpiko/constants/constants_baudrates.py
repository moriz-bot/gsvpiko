"""Baudrate constants for GSV serial communication.

The GSV-8 exposes more than one serial electrical interface. GSVmulti lists
separate baudrate sets for the 3.3 V UART/Ethernet path and for RS422. The
NPort RealCOM setup used by this project follows the UART/Ethernet set, not the
RS422 high-speed set.
"""

# GSV-8 UART 3.3 V / Ethernet / NPort-RealCOM path.
# 9600 is intentionally not included: GSVmulti does not list it for this path.
GSV8_UART_BAUDRATES = (
    19200,
    38400,
    57600,
    115200,
    230400,
    460800,
)

# GSV-8 RS422 path. These values are not valid for the UART/NPort-RealCOM path.
GSV8_RS422_BAUDRATES = (
    19200,
    38400,
    57600,
    115200,
    230400,
    460800,
    921600,
    1250000,
    1458333,
    1750000,
    2500000,
    3500000,
)

# Backwards-compatible name for code that only validates "known GSV-8 serial".
# Interface-specific code should prefer GSV8_UART_BAUDRATES or GSV8_RS422_BAUDRATES.
ALLOWED = tuple(dict.fromkeys((*GSV8_UART_BAUDRATES, *GSV8_RS422_BAUDRATES)))

ACTIVE_SERIAL_INTERFACE_SETTING_INDEX = 10
POWER_CYCLE_REQUIRED_FOR_STORED_CHANGE = True

# Probe order for the UART/NPort-RealCOM path. The preferred baudrate is
# always tried first by build_probe_order(), even if it is outside this fallback
# set, so diagnostic apps can still test 921600 explicitly.
UART_REALCOM_PROBE_ORDER = (
    460800,
    115200,
    230400,
    57600,
    38400,
    19200,
)

# Backwards-compatible name used by older diagnostics.
PROBE_ORDER = UART_REALCOM_PROBE_ORDER


def normalize_baudrate(
    baudrate: int | str,
    *,
    allowed: tuple[int, ...] = ALLOWED,
) -> int:
    """Return one validated GSV baudrate as an integer."""
    normalized_baudrate = int(baudrate)

    if normalized_baudrate not in allowed:
        raise ValueError(
            f"Unsupported GSV baudrate {normalized_baudrate}. "
            f"Allowed values are: {allowed}."
        )

    return normalized_baudrate


def normalize_uart_baudrate(
    baudrate: int | str,
) -> int:
    """Return one baudrate supported by the current UART/NPort path."""
    return normalize_baudrate(baudrate, allowed=GSV8_UART_BAUDRATES)


def normalize_rs422_baudrate(
    baudrate: int | str,
) -> int:
    """Return one baudrate supported by the GSV-8 RS422 path."""
    return normalize_baudrate(baudrate, allowed=GSV8_RS422_BAUDRATES)


def build_probe_order(
    preferred_baudrate: int | str,
    *,
    fallback_order: tuple[int, ...] = UART_REALCOM_PROBE_ORDER,
) -> tuple[int, ...]:
    """Return baudrates to try, starting with the preferred value.

    The preferred baudrate is validated against the union of known GSV-8 serial
    baudrates, while the fallback order defaults to the UART/NPort path. This
    keeps intentional diagnostics such as "try 921600 first, then fall back to
    460800" possible without treating 921600 as a normal UART fallback.
    """
    preferred = normalize_baudrate(preferred_baudrate)
    ordered = (preferred, *fallback_order)
    result = []

    for baudrate in ordered:
        if baudrate in result:
            continue
        result.append(baudrate)

    return tuple(result)
