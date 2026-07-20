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
py -m pip install "gsvpiko @ git+https://github.com/moriz-bot/gsvpiko.git@v0.1.2"
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
- CSV and text-report generation
- setup validation before measurement
- connection, runtime-rate and GSV status diagnostics
- external TCP control interface with a simple ASCII command protocol
- manual TCP client for testing the external control interface
- CSV plotting helper
- NPort mode switching via `transport_nport`  
  → no NPort Administrator required for the supported Real COM/TCP workflow
- baudrate probing  
  → automatic search for a working GSV-8 baudrate if the current device setting is unknown

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
AOutType_Mode = 0x02
AOutType_Enum = 0
```

and also with:

```text
AOutType_Mode = 0x02
AOutType_Enum = 5
```

In the observed setup, this analog-output hardware status did not prevent measurement output or recording.

## Repository structure

```text
src/gsvpiko/       Python package source code
docs/              project documentation and diagrams
references/        public reference documents used during development
README.md          project overview and installation notes
pyproject.toml     Python packaging metadata
LICENSE            license file
```

Important package areas:

```text
app/               command-line entry points
config/            device, sensor and setup configuration
coordination/      setup resolution, validation, recording and reporting logic
device/            GSV device abstraction
external/          external TCP control interface
features/          GSV feature groups
protocol/          frame building, parsing, payload coding and CRC
runtime/           runtime reading, routing and buffering
transport/         serial, TCP and NPort transport handling
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
gsvpiko-record-values
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
