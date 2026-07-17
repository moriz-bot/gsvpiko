# GSVpiko

GSVpiko is a Python package for configuring, reading, recording and diagnosing ME GSV-8 based measurement setups.

More information about GSVpiko in docs/ and about the measurement amplifier (= german: GleichSpannungsVerstärker = GSV) in references/.

## Install from a local checkout

```powershell
py -m pip install .
```

For development work, install the package in editable mode:

```powershell
py -m pip install -e .[dev]
```

## Command-line entry points

After installation, the main apps can be started directly from the terminal:

```powershell
gsvpiko-read-values --setup two_gsvs_two_sensors_each
gsvpiko-record-values --setup two_gsvs_two_sensors_each
gsvpiko-diagnose-errors --setup two_gsvs_two_sensors_each
gsvpiko-external-tcp-interface --host 127.0.0.1 --port 5050
gsvpiko-client-tcp --host 127.0.0.1 --port 5050
gsvpiko-plot-csv data/example.csv
```

The module form remains available:

```powershell
py -m gsvpiko.app.app_read_values_from_setup --setup two_gsvs_two_sensors_each
py -m gsvpiko.app.app_record_values_from_setup --setup two_gsvs_two_sensors_each
py -m gsvpiko.app.app_diagnose_gsv_status_errors --setup two_gsvs_two_sensors_each
py -m gsvpiko.app.client_tcp
py -m gsvpiko.app.plot_gsvpiko_csv data/example.csv
```

## Local output

Measurement CSV files, plots and diagnostic logs are runtime output. Keep them in `data/`, `logs/` or another local output directory and do not commit them to the package repository unless they are intentionally curated examples.
