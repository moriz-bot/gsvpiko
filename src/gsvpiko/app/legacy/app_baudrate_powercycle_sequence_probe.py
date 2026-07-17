"""Probe GSV serial-link baudrates with manual GSV and NPort steps.

This diagnostic walks through baudrates sequentially. It starts from a known
working serial-link baudrate, stores the next target baudrate in the GSV, waits
for the user to power-cycle the GSV, optionally tests the expected mismatch
state, waits for the user to change the NPort serial baudrate, and then tests the
matched state.

The app does not change the NPort configuration. For TCP Server mode, the
baudrate in this diagnostic is still the serial-link baudrate between NPort and
GSV; the TCP data port normally remains 4001.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import config_devices as DEVICE
from ..constants import constants_baudrates as BAUDRATE
from ..device.device_gsv import GsvDevice
from ..transport.transport_serial import SerialTransport
from ..transport.transport_tcp import TcpTransport


CONNECTION_TYPE_SERIAL = "serial"
CONNECTION_TYPE_TCP = "tcp"

START_BAUDRATE = 460800
SAFE_SAMPLE_RATE_HZ = 10.0
DEFAULT_INTERFACE_SETTING_INDEX = BAUDRATE.ACTIVE_SERIAL_INTERFACE_SETTING_INDEX
DEFAULT_TIMEOUT_S = 1.0
DEFAULT_RESULTS_DIR = Path("docs")

DEFAULT_TARGET_BAUDRATES = (
    START_BAUDRATE,
    230400,
    115200,
    57600,
    38400,
    19200,
    921600,
    1250000,
    1458333,
    1750000,
    2500000,
    3500000,
)


@dataclass
class ProbeEvent:
    """One result row from the manual baudrate probe."""

    timestamp: str
    device_name: str
    connection_type: str
    ip_address: str | None
    com_port: str | None
    tcp_port: int | None
    interface_setting_index: int
    current_link_baudrate: int
    target_baudrate: int
    phase: str
    ok: bool
    response_raw_hex: str = ""
    stored_baudrate_before: int | None = None
    stored_baudrate_after: int | None = None
    sample_rate_before_hz: float | None = None
    sample_rate_after_hz: float | None = None
    error: str = ""

    def to_row(self) -> dict[str, Any]:
        """Return a CSV-ready row."""
        return {
            "timestamp": self.timestamp,
            "device_name": self.device_name,
            "connection_type": self.connection_type,
            "ip_address": self.ip_address,
            "com_port": self.com_port,
            "tcp_port": self.tcp_port,
            "interface_setting_index": self.interface_setting_index,
            "current_link_baudrate": self.current_link_baudrate,
            "target_baudrate": self.target_baudrate,
            "phase": self.phase,
            "ok": self.ok,
            "response_raw_hex": self.response_raw_hex,
            "stored_baudrate_before": self.stored_baudrate_before,
            "stored_baudrate_after": self.stored_baudrate_after,
            "sample_rate_before_hz": self.sample_rate_before_hz,
            "sample_rate_after_hz": self.sample_rate_after_hz,
            "error": self.error,
        }


def parse_int_list(text: str) -> tuple[int, ...]:
    """Parse comma-separated integer values."""
    values: list[int] = []
    for part in text.split(","):
        stripped = part.strip()
        if stripped:
            values.append(int(stripped))

    if not values:
        raise argparse.ArgumentTypeError("At least one integer value is required.")

    return tuple(values)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Probe GSV baudrates with manual GSV power-cycles and NPort changes."
    )
    parser.add_argument(
        "--devices",
        default="default",
        help=(
            "Device selection: 'default', 'all', or comma-separated preset names. "
            "Default: default."
        ),
    )
    parser.add_argument(
        "--baudrates",
        type=parse_int_list,
        default=DEFAULT_TARGET_BAUDRATES,
        help=(
            "Comma-separated target baudrates. The start baudrate is tested first "
            "even if it is not the first value here. Default: "
            + ",".join(str(value) for value in DEFAULT_TARGET_BAUDRATES)
        ),
    )
    parser.add_argument(
        "--start-baudrate",
        type=int,
        default=START_BAUDRATE,
        help=(
            "Known working serial-link baudrate at app start. "
            f"Default: {START_BAUDRATE}."
        ),
    )
    parser.add_argument(
        "--safe-sample-rate-hz",
        type=float,
        default=SAFE_SAMPLE_RATE_HZ,
        help=(
            "Sample rate written before baudrate changes so lower baudrates are not "
            "rejected because of the current output data rate. "
            f"Default: {SAFE_SAMPLE_RATE_HZ}."
        ),
    )
    parser.add_argument(
        "--index",
        type=int,
        default=DEFAULT_INTERFACE_SETTING_INDEX,
        help=f"Interface-setting index to write. Default: {DEFAULT_INTERFACE_SETTING_INDEX}.",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"Transport timeout used for each open/test step. Default: {DEFAULT_TIMEOUT_S}.",
    )
    parser.add_argument(
        "--results-file",
        default="",
        help="Optional CSV result path. Default: docs/baudrate_powercycle_sequence_<timestamp>.csv.",
    )
    parser.add_argument(
        "--skip-mismatch-test",
        action="store_true",
        help="Skip the test after GSV power-cycle but before changing the NPort baudrate.",
    )
    return parser.parse_args()


def selected_device_configs(selection: str) -> list[dict[str, Any]]:
    """Return device presets selected by a CLI string."""
    normalized = selection.strip()

    if normalized.lower() == "default":
        return [DEVICE.DEFAULT_DEVICE]

    if normalized.lower() == "all":
        return [DEVICE.DEVICE_PRESETS[name] for name in sorted(DEVICE.DEVICE_PRESETS)]

    result = []
    for name in normalized.split(","):
        stripped = name.strip()
        if stripped not in DEVICE.DEVICE_PRESETS:
            raise ValueError(
                f"Unknown device preset {stripped!r}. Known presets: {sorted(DEVICE.DEVICE_PRESETS)}."
            )
        result.append(DEVICE.DEVICE_PRESETS[stripped])

    return result


def ordered_targets(
    *,
    start_baudrate: int,
    requested_targets: tuple[int, ...],
) -> tuple[int, ...]:
    """Return targets with the start baudrate tested first and no duplicates."""
    result: list[int] = []
    for baudrate in (start_baudrate, *requested_targets):
        normalized = int(baudrate)
        if normalized in result:
            continue
        result.append(normalized)
    return tuple(result)


def timestamp_now() -> str:
    """Return an ISO-like timestamp for result rows."""
    return datetime.now().isoformat(timespec="seconds")


def default_results_file() -> Path:
    """Return the default CSV result path."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return DEFAULT_RESULTS_DIR / f"baudrate_powercycle_sequence_{stamp}.csv"


def create_device_for_link_baudrate(
    device_config: dict[str, Any],
    *,
    link_baudrate: int,
    timeout_s: float,
) -> GsvDevice:
    """Create one unopened device for the current serial-link baudrate.

    For TCP, link_baudrate is not applied to the socket. It is still recorded in
    the result because it must match the NPort serial setting and the active GSV
    serial setting.
    """
    connection_type = device_config.get("default_connection_type", CONNECTION_TYPE_SERIAL)

    if connection_type == CONNECTION_TYPE_TCP:
        transport = TcpTransport(
            host=device_config["ip_address"],
            port=int(device_config["tcp_port"]),
            timeout=timeout_s,
        )
    elif connection_type == CONNECTION_TYPE_SERIAL:
        transport = SerialTransport(
            port=device_config["com_port"],
            baudrate=int(link_baudrate),
            timeout=timeout_s,
        )
    else:
        raise ValueError(
            f"Unsupported default_connection_type {connection_type!r}. "
            f"Expected {CONNECTION_TYPE_SERIAL!r} or {CONNECTION_TYPE_TCP!r}."
        )

    return GsvDevice(
        transport,
        name=device_config["name"],
    )


def open_verified_device(
    device_config: dict[str, Any],
    *,
    link_baudrate: int,
    timeout_s: float,
) -> GsvDevice:
    """Open one device and verify that a GSV responds to StopTransmission."""
    device = create_device_for_link_baudrate(
        device_config,
        link_baudrate=link_baudrate,
        timeout_s=timeout_s,
    )

    try:
        device.open()
        device.clear_input_buffer()
        device.acquisition.stop_transmission()
        device.clear_input_buffer()
        return device
    except Exception:
        close_device_quietly(device)
        raise


def close_device_quietly(device: GsvDevice | None) -> None:
    """Close a device object and ignore close errors."""
    if device is None:
        return

    try:
        device.close()
    except Exception:
        pass


def read_stored_baudrate(device: GsvDevice, *, index: int) -> int | None:
    """Read one interface-setting value, returning None on error."""
    try:
        return int(device.interface.read_interface_setting(index)["data"])
    except Exception:
        return None


def read_sample_rate(device: GsvDevice) -> float | None:
    """Read the active output sample rate, returning None on error."""
    try:
        return float(device.acquisition.read_sample_rate()["sample_rate_hz"])
    except Exception:
        return None


def event_from_result(
    *,
    device_config: dict[str, Any],
    index: int,
    current_link_baudrate: int,
    target_baudrate: int,
    phase: str,
    ok: bool,
    response_raw_hex: str = "",
    stored_baudrate_before: int | None = None,
    stored_baudrate_after: int | None = None,
    sample_rate_before_hz: float | None = None,
    sample_rate_after_hz: float | None = None,
    error: str = "",
) -> ProbeEvent:
    """Build one result event."""
    return ProbeEvent(
        timestamp=timestamp_now(),
        device_name=device_config["name"],
        connection_type=device_config.get("default_connection_type", CONNECTION_TYPE_SERIAL),
        ip_address=device_config.get("ip_address"),
        com_port=device_config.get("com_port"),
        tcp_port=device_config.get("tcp_port"),
        interface_setting_index=index,
        current_link_baudrate=int(current_link_baudrate),
        target_baudrate=int(target_baudrate),
        phase=phase,
        ok=ok,
        response_raw_hex=response_raw_hex,
        stored_baudrate_before=stored_baudrate_before,
        stored_baudrate_after=stored_baudrate_after,
        sample_rate_before_hz=sample_rate_before_hz,
        sample_rate_after_hz=sample_rate_after_hz,
        error=error,
    )


def test_link(
    *,
    device_config: dict[str, Any],
    index: int,
    current_link_baudrate: int,
    target_baudrate: int,
    phase: str,
    timeout_s: float,
) -> ProbeEvent:
    """Open one device and verify that the GSV responds on the current link."""
    device = None

    try:
        device = open_verified_device(
            device_config,
            link_baudrate=current_link_baudrate,
            timeout_s=timeout_s,
        )
        stored = read_stored_baudrate(device, index=index)
        response = device.acquisition.stop_transmission()
        return event_from_result(
            device_config=device_config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            phase=phase,
            ok=True,
            response_raw_hex=response.get("raw_hex", ""),
            stored_baudrate_after=stored,
        )
    except Exception as error:
        return event_from_result(
            device_config=device_config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            phase=phase,
            ok=False,
            error=str(error),
        )
    finally:
        close_device_quietly(device)


def prepare_safe_sample_rate(
    *,
    device_config: dict[str, Any],
    index: int,
    current_link_baudrate: int,
    target_baudrate: int,
    safe_sample_rate_hz: float,
    timeout_s: float,
) -> ProbeEvent:
    """Stop transmission and set a low sample rate before baudrate changes."""
    device = None
    before = None
    after = None

    try:
        device = open_verified_device(
            device_config,
            link_baudrate=current_link_baudrate,
            timeout_s=timeout_s,
        )
        device.acquisition.stop_transmission()
        before = read_sample_rate(device)
        response = device.acquisition.configure_sample_rate(safe_sample_rate_hz)
        after = float(response["sample_rate_hz"])
        return event_from_result(
            device_config=device_config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            phase="prepare_safe_sample_rate",
            ok=True,
            response_raw_hex=response.get("raw_hex", ""),
            sample_rate_before_hz=before,
            sample_rate_after_hz=after,
        )
    except Exception as error:
        return event_from_result(
            device_config=device_config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            phase="prepare_safe_sample_rate",
            ok=False,
            sample_rate_before_hz=before,
            sample_rate_after_hz=after,
            error=str(error),
        )
    finally:
        close_device_quietly(device)


def write_target_baudrate(
    *,
    device_config: dict[str, Any],
    index: int,
    current_link_baudrate: int,
    target_baudrate: int,
    timeout_s: float,
) -> ProbeEvent:
    """Open one device at the current link baudrate and store a new target baudrate."""
    device = None
    stored_before = None
    stored_after = None

    try:
        device = open_verified_device(
            device_config,
            link_baudrate=current_link_baudrate,
            timeout_s=timeout_s,
        )
        device.acquisition.stop_transmission()
        stored_before = read_stored_baudrate(device, index=index)
        response = device.interface.write_interface_setting(
            index=index,
            data=int(target_baudrate),
        )
        stored_after = read_stored_baudrate(device, index=index)

        try:
            device.interface.release_interface()
        except Exception as error:
            print(f"ReleaseInterface failed after write: {error}")

        return event_from_result(
            device_config=device_config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            phase="write_target_to_gsv",
            ok=True,
            response_raw_hex=response.get("raw_hex", ""),
            stored_baudrate_before=stored_before,
            stored_baudrate_after=stored_after,
        )
    except Exception as error:
        return event_from_result(
            device_config=device_config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            phase="write_target_to_gsv",
            ok=False,
            stored_baudrate_before=stored_before,
            stored_baudrate_after=stored_after,
            error=str(error),
        )
    finally:
        close_device_quietly(device)


def print_event(event: ProbeEvent) -> None:
    """Print one compact event result."""
    status = "OK" if event.ok else "FAILED"
    print(f"{event.device_name} | {event.phase} | target={event.target_baudrate}: {status}")

    if event.response_raw_hex:
        print(f"  response: {event.response_raw_hex}")

    print(f"  current_link_baudrate: {event.current_link_baudrate}")

    if event.stored_baudrate_before is not None:
        print(f"  stored_before: {event.stored_baudrate_before}")

    if event.stored_baudrate_after is not None:
        print(f"  stored_after: {event.stored_baudrate_after}")

    if event.sample_rate_before_hz is not None:
        print(f"  sample_rate_before_hz: {event.sample_rate_before_hz:g}")

    if event.sample_rate_after_hz is not None:
        print(f"  sample_rate_after_hz: {event.sample_rate_after_hz:g}")

    if event.error:
        print(f"  error: {event.error}")


def prompt_enter(message: str) -> None:
    """Wait until the user presses Enter."""
    print()
    input(message)
    print()


def write_results_file(*, path: Path, events: list[ProbeEvent]) -> None:
    """Write all probe events to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [event.to_row() for event in events]

    if not rows:
        return

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def print_change_instructions(
    *,
    device_configs: list[dict[str, Any]],
    current_link_baudrate: int,
    target_baudrate: int,
) -> None:
    """Print the manual steps needed after writing a target baudrate."""
    print()
    print(f"Manual steps: {current_link_baudrate} -> {target_baudrate}")
    print("-" * (19 + len(str(current_link_baudrate)) + len(str(target_baudrate))))
    print("1. Leave the NPort Serial Settings baudrate unchanged for the first test.")
    print("2. Power-cycle only the GSV device(s). The stored GSV baudrate becomes active now.")
    print("3. Press Enter. The app tests the expected mismatch state.")
    print("4. Set the NPort Serial Settings baudrate to the same target value:")
    for config in device_configs:
        print(
            f"   - {config['name']}: NPort/IP={config.get('ip_address')}, "
            f"target={target_baudrate}, TCP port={config.get('tcp_port')}"
        )
    print("5. Save/apply the NPort setting if required by the NPort tool.")
    print("6. Press Enter. The app tests the matched state.")


def print_restore_hint(current_link_baudrate: int) -> None:
    """Print a concise recovery hint when a target did not become reachable."""
    print()
    print("Recovery hint")
    print("-------------")
    print(f"Set GSV and NPort back to the last working baudrate: {current_link_baudrate}.")
    print("Then rerun the app with --start-baudrate set to that working baudrate.")


def run_initial_test(
    *,
    device_configs: list[dict[str, Any]],
    index: int,
    current_link_baudrate: int,
    timeout_s: float,
) -> list[ProbeEvent]:
    """Test the initial matched baudrate before any write is made."""
    print()
    print(f"Initial link test at start baudrate: {current_link_baudrate}")
    print("-" * (42 + len(str(current_link_baudrate))))
    events = []

    for config in device_configs:
        event = test_link(
            device_config=config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=current_link_baudrate,
            phase="initial_start_baudrate_test",
            timeout_s=timeout_s,
        )
        print_event(event)
        events.append(event)

    return events


def run_for_target(
    *,
    device_configs: list[dict[str, Any]],
    current_link_baudrate: int,
    target_baudrate: int,
    index: int,
    safe_sample_rate_hz: float,
    timeout_s: float,
    skip_mismatch_test: bool,
) -> tuple[list[ProbeEvent], int]:
    """Run one sequential baudrate change and return events plus new working baudrate."""
    events: list[ProbeEvent] = []

    print()
    print(f"Target baudrate: {target_baudrate}")
    print("=" * (17 + len(str(target_baudrate))))
    print(f"current_link_baudrate: {current_link_baudrate}")

    if target_baudrate == current_link_baudrate:
        print("Target equals current link baudrate; only testing the current matched state.")
        for config in device_configs:
            event = test_link(
                device_config=config,
                index=index,
                current_link_baudrate=current_link_baudrate,
                target_baudrate=target_baudrate,
                phase="target_already_active_test",
                timeout_s=timeout_s,
            )
            print_event(event)
            events.append(event)
        return events, current_link_baudrate

    print("Preparing safe sample rate before the baudrate write")
    print("----------------------------------------------------")
    prepare_events = []
    for config in device_configs:
        event = prepare_safe_sample_rate(
            device_config=config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            safe_sample_rate_hz=safe_sample_rate_hz,
            timeout_s=timeout_s,
        )
        print_event(event)
        prepare_events.append(event)
        events.append(event)

    if not all(event.ok for event in prepare_events):
        print("At least one device could not be prepared. Target skipped.")
        return events, current_link_baudrate

    print()
    print("Writing target baudrate to GSV")
    print("--------------------------------")
    write_events = []
    for config in device_configs:
        event = write_target_baudrate(
            device_config=config,
            index=index,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            timeout_s=timeout_s,
        )
        print_event(event)
        write_events.append(event)
        events.append(event)

    if not all(event.ok for event in write_events):
        print("At least one write failed. This target is skipped; the current link baudrate is unchanged.")
        return events, current_link_baudrate

    print_change_instructions(
        device_configs=device_configs,
        current_link_baudrate=current_link_baudrate,
        target_baudrate=target_baudrate,
    )

    if not skip_mismatch_test:
        prompt_enter(
            "Power-cycle only the GSV device(s), leave NPort unchanged, then press Enter..."
        )
        print("Testing expected mismatch before NPort baudrate change")
        print("------------------------------------------------------")
        for config in device_configs:
            event = test_link(
                device_config=config,
                index=index,
                current_link_baudrate=current_link_baudrate,
                target_baudrate=target_baudrate,
                phase="after_gsv_power_cycle_before_nport_change",
                timeout_s=timeout_s,
            )
            print_event(event)
            events.append(event)

    prompt_enter("Set NPort serial baudrate to target, apply if required, then press Enter...")
    print("Testing matched state after NPort baudrate change")
    print("-------------------------------------------------")
    matched_events = []
    for config in device_configs:
        event = test_link(
            device_config=config,
            index=index,
            current_link_baudrate=target_baudrate,
            target_baudrate=target_baudrate,
            phase="after_nport_change_matched_test",
            timeout_s=timeout_s,
        )
        print_event(event)
        matched_events.append(event)
        events.append(event)

    if all(event.ok for event in matched_events):
        print(f"Target {target_baudrate} is now the working link baudrate.")
        return events, target_baudrate

    print("Matched-state test failed. The app will keep the previous working baudrate internally.")
    print_restore_hint(current_link_baudrate)
    return events, current_link_baudrate


def main() -> None:
    """Run the interactive baudrate sequence."""
    args = parse_args()
    device_configs = selected_device_configs(args.devices)
    targets = ordered_targets(
        start_baudrate=int(args.start_baudrate),
        requested_targets=tuple(int(value) for value in args.baudrates),
    )
    current_link_baudrate = int(args.start_baudrate)
    results_path = Path(args.results_file) if args.results_file else default_results_file()
    events: list[ProbeEvent] = []

    print("GSV baudrate power-cycle sequence probe")
    print("---------------------------------------")
    print("devices: " + ", ".join(config["name"] for config in device_configs))
    print("target_baudrates: " + ", ".join(str(value) for value in targets))
    print(f"start_baudrate: {current_link_baudrate}")
    print(f"safe_sample_rate_hz: {args.safe_sample_rate_hz:g}")
    print(f"interface_setting_index: {args.index}")
    print(f"timeout_s: {args.timeout_s}")
    print(f"results_file: {results_path}")
    print()
    print("This app changes only the GSV baudrate setting.")
    print("It cannot read the active GSV baudrate directly before communication works.")
    print("It verifies the start state by checking whether the GSV responds at start_baudrate.")
    print("The NPort serial baudrate must be changed manually when the app asks for it.")

    prompt_enter(
        "Set/check the NPort Serial Settings baudrate to start_baudrate, then press Enter..."
    )

    initial_events = run_initial_test(
        device_configs=device_configs,
        index=args.index,
        current_link_baudrate=current_link_baudrate,
        timeout_s=args.timeout_s,
    )
    events.extend(initial_events)
    write_results_file(path=results_path, events=events)

    if not all(event.ok for event in initial_events):
        print()
        print("Initial test failed.")
        print("The app cannot know the GSV baudrate without a working connection.")
        print("Set NPort and GSV back to a known matching baudrate, then rerun with --start-baudrate.")
        print(f"Partial CSV written: {results_path}")
        return

    for target_baudrate in targets:
        target_events, current_link_baudrate = run_for_target(
            device_configs=device_configs,
            current_link_baudrate=current_link_baudrate,
            target_baudrate=target_baudrate,
            index=args.index,
            safe_sample_rate_hz=args.safe_sample_rate_hz,
            timeout_s=args.timeout_s,
            skip_mismatch_test=args.skip_mismatch_test,
        )
        events.extend(target_events)
        write_results_file(path=results_path, events=events)
        print(f"Partial CSV written: {results_path}")

    print()
    print("Probe finished.")
    print(f"CSV written: {results_path}")


if __name__ == "__main__":
    main()
