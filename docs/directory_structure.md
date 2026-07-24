# GSVpiko – Directory Structure

This is the intended repository structure for the current package-oriented state @v0.1.4.
Planned but unavailable parts are marked with `not implemented`.

## Project tree

```text
GSVpiko/
│
├── .gitignore
├── README.md
├── pyproject.toml
│
├── docs/
│   ├── directory_structure.md
│   ├── layered_architecture.svg
│   ├── module_alias_convention.md
│   └── sequence_diagram_recording_example.svg
│
├── references/
│   ├── GSV-ProtocolDefinition.pdf
│   ├── ba-gsv8.pdf
│   ├── ba-gsvmulti.pdf
│   └── gsv86lib_github.url
│
├── src/
│   └── gsvpiko/
│       ├── __init__.py
│       │
│       ├── app/
│       │   ├── __init__.py
│       │   ├── _cli_options.py
│       │   ├── _setup_selection.py
│       │   ├── app_diagnose_connection.py
│       │   ├── app_diagnose_gsv_status_errors.py
│       │   ├── app_diagnose_runtime_rates.py
│       │   ├── app_external_tcp_interface.py
│       │   ├── app_read_values_from_setup.py
│       │   ├── app_record.py
│       │   ├── app_setup_application.py
│       │   ├── app_setup_validation.py
│       │   ├── client_tcp.py
│       │   ├── plot_gsvpiko_csv.py
│       │   └── legacy/
│       │       └── ...
│       │
│       ├── config/
│       │   ├── __init__.py
│       │   ├── config_device_template.py
│       │   ├── config_devices.py
│       │   ├── config_sensors/
│       │   │   ├── __init__.py
│       │   │   ├── sensor_k3d40_24200767.py
│       │   │   ├── sensor_k3d40_24200770.py
│       │   │   ├── sensor_k3d40_25202514.py
│       │   │   ├── sensor_k3d40_25202515.py
│       │   │   └── sensor_template.py
│       │   └── config_setups/
│       │       ├── __init__.py
│       │       ├── setup_one_gsv_one_sensor_1_3.py
│       │       ├── setup_one_gsv_one_sensor_1_6.py
│       │       ├── setup_one_gsv_two_sensors.py
│       │       ├── setup_template.py
│       │       ├── setup_three_gsvs_four_sensors.py
│       │       ├── setup_two_gsvs_one_sensor_each.py
│       │       └── setup_two_gsvs_two_sensors_each.py
│       │
│       ├── constants/
│       │   ├── __init__.py
│       │   ├── constants_analog_filters.py
│       │   ├── constants_baudrates.py
│       │   ├── constants_commands.py
│       │   ├── constants_datatypes.py
│       │   ├── constants_digital_io.py
│       │   ├── constants_errors.py
│       │   ├── constants_errors_value.py
│       │   ├── constants_frames.py
│       │   ├── constants_interfaces.py
│       │   ├── constants_quantities.py
│       │   ├── constants_sensor_input_modes.py
│       │   ├── constants_sockets.py
│       │   └── constants_units.py
│       │
│       ├── coordination/
│       │   ├── __init__.py
│       │   ├── coordination_diagnostics.py
│       │   ├── coordination_recording.py
│       │   ├── coordination_sample_rate_limit.py
│       │   ├── coordination_sensor_validation.py
│       │   ├── coordination_setup_application.py
│       │   ├── coordination_setup_resolution.py
│       │   └── coordination_setup_validation.py
│       │
│       ├── device/
│       │   ├── __init__.py
│       │   ├── device_channels.py
│       │   ├── device_connection.py
│       │   ├── device_connection_report.py
│       │   ├── device_gsv.py
│       │   ├── device_measurement.py
│       │   └── device_report.py
│       │
│       ├── external/
│       │   ├── __init__.py
│       │   ├── external_ascii_protocol.py
│       │   └── external_tcp_interface.py
│       │
│       ├── features/
│       │   ├── __init__.py
│       │   ├── feature_acquisition.py
│       │   ├── feature_admin.py
│       │   ├── feature_filters.py
│       │   ├── feature_input.py
│       │   ├── feature_interface.py
│       │   ├── feature_scaling.py
│       │   └── feature_zero.py
│       │   # feature_counter.py              # not implemented
│       │   # feature_filesystem.py           # not implemented
│       │   # feature_ft_sensor.py            # not implemented
│       │   # feature_io.py                   # not implemented
│       │   # feature_logger.py               # not implemented
│       │   # feature_output.py               # not implemented
│       │   # feature_teds.py                 # not implemented
│       │
│       ├── output/
│       │   ├── __init__.py
│       │   ├── output_csv.py
│       │   ├── output_paths.py
│       │   ├── output_plot.py
│       │   ├── output_report.py
│       │   └── output_report_print.py
│       │
│       ├── protocol/
│       │   ├── __init__.py
│       │   ├── protocol_crc.py
│       │   ├── protocol_frame_builder.py
│       │   ├── protocol_frame_parser.py
│       │   └── protocol_payload_codec.py
│       │
│       ├── runtime/
│       │   ├── __init__.py
│       │   ├── runtime_measurement_buffer.py
│       │   ├── runtime_reader.py
│       │   ├── runtime_report.py
│       │   ├── runtime_router.py
│       │   └── runtime_session.py
│       │
│       ├── transport/
│       │   ├── __init__.py
│       │   ├── transport_base.py
│       │   ├── transport_factory.py
│       │   ├── transport_nport.py
│       │   ├── transport_serial.py
│       │   └── transport_tcp.py
│       │
│       └── utils/
│           ├── __init__.py
│           ├── utils_duration.py
│           └── utils_hex.py
│
└── tests/                                  # not implemented
```

## Runtime output

```text
gsvpiko_data/                                  # local measurement CSV/PNG output, not tracked
gsvpiko_logs/                                  # local diagnostic and recording logs, not tracked
```

