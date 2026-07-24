# GSVpiko

GSVpiko is a Python package for configuring, reading, recording and diagnosing ME GSV-8 measurement amplifiers. GSV is short for the German term GleichSpannungsVerstärker.

It includes project-specific configuration files for multiple real GSV-8 devices, sensors and setups. The NPort Administrator is not required for the supported workflow.

More information about GSVpiko is available in `docs/`. Reference material for the GSV measurement amplifier is available in `references/`.

## Installation

Choose one installation method.

### PyPI

Recommended for normal use:

```powershell
py -m pip install gsvpiko
```

On systems where `python` is available instead of the Windows `py` launcher:

```bash
python -m pip install gsvpiko
```

Check the installation:

```powershell
gsvpiko-client-tcp --help
```

If the command is not found on Windows, the Python `Scripts` directory may not be in `PATH`. The package is still installed in the Python environment that ran `pip`.

### GitHub

Install the current repository state:

```powershell
py -m pip install "gsvpiko @ git+https://github.com/moriz-bot/gsvpiko.git"
```

Install a specific tagged version:

```powershell
py -m pip install "gsvpiko @ git+https://github.com/moriz-bot/gsvpiko.git@v0.1.4"
```

### Local checkout

Clone and install the local project:

```powershell
git clone https://github.com/moriz-bot/gsvpiko.git
cd gsvpiko
py -m pip install .
```

For development:

```powershell
py -m pip install -e .
```

`-e` means editable mode: local source-code changes are used directly without reinstalling.

## Version check

```powershell
py -c "import gsvpiko; print(gsvpiko.__version__)"
```

or directly from package metadata:

```powershell
py -c "from importlib.metadata import version; print(version('gsvpiko'))"
```

## Main features

- setup-based configuration of ME GSV-8 measurement amplifiers
- multiple GSV devices + multiple 3-axis sensors
- real device, sensor and setup configuration files
- sensor scaling and software-side crosstalk compensation
- reading and recording measurement values
- CSV, text-report and PNG plot generation
- event markers in plots for GSVpiko runtime commands such as `tare`
- setup validation before measurement
- connection, runtime-rate and GSV status diagnostics
- external TCP control interface with a simple ASCII command protocol
- manual TCP client for testing the external control interface
- local interactive recording shell via `gsvpiko-record`
- CSV plotting helper via `gsvpiko-plot-csv`
- NPort mode switching via `transport_nport`  
  → no NPort Administrator required for the supported Real COM/TCP workflow
- baudrate probing  
  → automatic search for a working GSV-8 baudrate if the current device setting is unknown

## Recording workflow

The local recording app is started with:

```powershell
gsvpiko-record
```

The interactive workflow separates transmission from recorded capture windows:

```text
session ipc_test01   tare if configured and start GSV transmission
start                start storing samples
stop                 pause storing samples while transmission continues
start 20 s           store samples for 20 seconds, then stop automatically
save                 stop transmission and write CSV/report/PNG
quit                 save an active session if needed and close the program
```

`start 20s`, `start 30m` and `start 4h` are accepted in addition to the spaced forms `start 20 s`, `start 30 m` and `start 4 h`. `tare` is only run at `session` start when the setup has `zero_before_recording=True`, or when the user explicitly enters `tare`. `start` never runs an automatic tare.

The external TCP interface uses the same session workflow with single-line responses for clients:

```text
SESSION ipc_test01
START 20S
START 20S
SAVE
```

## Transport and NPort support

Typical hardware chain:

```text
GSV-8 → serial interface → NPort → Ethernet → computer
```

Supported NPort operating modes:

```text
NPort Real COM Mode   → GSVpiko transport: serial
NPort TCP Server Mode → GSVpiko transport: tcp
```

`transport_nport` can switch the NPort operating mode automatically. This is especially useful when moving between serial-style access and direct TCP access without manually changing the NPort configuration in a separate administration tool.

## Output folders

Default runtime output is written relative to the current working directory:

```text
gsvpiko_data/     CSV files and PNG plots
gsvpiko_logs/     text reports
```

The recording app supports process-local overrides:

```powershell
gsvpiko-record --data-dir C:\Measurements\GSVpikoData --log-dir C:\Measurements\GSVpikoLogs
```

The local recording shell and the external TCP interface also support persistent output folders through their `path` command. Persistent settings are stored in the current user's GSVpiko settings file.

## Baudrate probing

A GSV-8 connection can fail if the host uses a different baudrate than the device. GSVpiko includes baudrate probing utilities that test supported baudrates automatically until communication with the amplifier is established.

This is useful when the current GSV-8 baudrate is unknown or was changed previously.

Tested result for the used GSV-8/NPort setup:

```text
accepted: 460800 bit/s
rejected: 921600 bit/s
```

Therefore, `460800 bit/s` is the highest tested accepted baudrate for this setup.

## Tested sample-rate limits

For one 3-channel sensor at `460800 bit/s`, the conservative largest streamed datatype is `float32`.

Estimated communication limit for `float32`:

```text
2880 Hz
```

Tested and GSV-accepted rounded-down operating value:

```text
2400 Hz
```

Additional short-test values:

```text
float32 → 2400 Hz
int24   → 3200 Hz
int16   → 4000 Hz
```

For conservative operation with one 3-channel sensor, `float32` at `2400 Hz` is the practical tested upper value.

## Known hardware status observation

🔴 `HARDWARE_ERROR_ANALOG_OUTPUT (0xFFFF)`

On the tested hardware, this status can still occur on the affected GSV device and can cause the red MOD LED/button indication to blink.

It was observed even after setting the analog outputs inactive through `SetAOutType`-style configuration values:

```text
AOutType_Mode = 0x02  (inactive)
AOutType_Enum = 5     (OFF)
```

In the observed setup, this analog-output hardware status did not prevent measurement output or recording.

## Repository structure

```text
src/gsvpiko/       Python package source code
docs/              project documentation and diagrams
references/        public reference documents used during development
gsvpiko_data/      local runtime CSV and plot output, not committed
gsvpiko_logs/      local runtime report output, not committed
README.md          project overview and installation notes
pyproject.toml     Python packaging metadata
LICENSE            license file
```

Important package areas:

```text
app/               command-line entry points and local interactive apps
config/            device, sensor and setup configuration
coordination/      setup resolution, validation, diagnostics and recording orchestration
device/            GSV device abstraction
external/          external TCP control interface
features/          GSV feature groups
output/            CSV, report, plot and output-path handling
protocol/          frame building, parsing, payload coding and CRC
runtime/           runtime reading, routing and buffering
transport/         serial, TCP and NPort transport handling
utils/             small generic helpers
```

## Basic command examples

Validate a configured setup:

```powershell
gsvpiko-setup-validation
```

Apply a configured setup:

```powershell
gsvpiko-setup-application
```

Read values from a setup:

```powershell
gsvpiko-read-values
```

Record values from a setup:

```powershell
gsvpiko-record
```

Run the external TCP interface:

```powershell
gsvpiko-external-tcp-interface
```

Run the manual TCP client:

```powershell
gsvpiko-client-tcp
```

Plot a GSVpiko CSV file:

```powershell
gsvpiko-plot-csv path\to\file.csv
```

## License

GSVpiko is distributed under the MIT License. See `LICENSE`.
