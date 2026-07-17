# GSVpiko – Module Alias Convention

## Rule

- Import project modules as modules, not as loose groups of constants or functions, when the imported module is used repeatedly.
- Use a short ALLCAPS alias for constant/config modules.
- Use topic-based ALLCAPS aliases for coordination/config registries where this improves readability.
- Use classes and single functions directly only when that is the clearer local API boundary.
- Use imported constants as `ALIAS.NAME`.

## Constants

```python
from ..constants import constants_analog_filters as ANALOG_FILTER
from ..constants import constants_baudrates as BAUDRATE
from ..constants import constants_commands as COMMAND
from ..constants import constants_datatypes as DATATYPE
from ..constants import constants_digital_io as DIGITAL_IO
from ..constants import constants_errors as ERROR
from ..constants import constants_errors_value as VALUE_ERROR
from ..constants import constants_frames as FRAME
from ..constants import constants_interfaces as INTERFACE
from ..constants import constants_quantities as QUANTITY
from ..constants import constants_sensor_input_modes as SENSOR_INPUT_MODE
from ..constants import constants_sockets as SOCKET
from ..constants import constants_units as UNIT
```

## Config registries

```python
from ..config import config_devices as DEVICE
from ..config import config_setups as SETUP
from ..config import config_sensors as SENSOR
```

The setup and sensor packages expose named presets. Use the exported preset names instead of duplicating setup or sensor dictionaries in apps.

```python
SETUP.TWO_GSVS_TWO_SENSORS_EACH
SENSOR.K3D40_24200767
```

## Coordination and feature modules

Use direct class/function imports for stable service boundaries:

```python
from ..features.feature_admin import AdminFeature
from ..features.feature_acquisition import AcquisitionFeature
from ..coordination.coordination_setup_resolution import resolve_setup
from ..coordination.coordination_setup_application import open_and_apply_setup
```

Use module aliases for larger grouped helper APIs:

```python
from ..coordination import coordination_sample_rate_limit as SAMPLE_RATE_LIMIT
from ..coordination import coordination_sensor_validation as SENSOR_VALIDATION
```

## Protocol, transport and utilities

```python
from ..protocol import protocol_frame_builder as FRAME_BUILDER
from ..protocol import protocol_frame_parser as FRAME_PARSER
from ..protocol import protocol_payload_codec as PAYLOAD
from ..transport import transport_nport as NPORT
from ..utils import utils_hex as HEX
```

## Examples

```python
COMMAND.START_TRANSMISSION
DATATYPE.FLOAT32
ERROR.OK
VALUE_ERROR.HARDWARE_ERROR_ANALOG_OUTPUT
INTERFACE.UART
SOCKET.SOCKET_1_3
SENSOR_INPUT_MODE.MV_PER_V_3_5
UNIT.NEWTON

setup = SETUP.TWO_GSVS_TWO_SENSORS_EACH
sensor = SENSOR.K3D40_24200767
```

## Avoid

```python
from ..constants.constants_commands import START_TRANSMISSION, STOP_TRANSMISSION
from ..config.config_setups.setup_two_gsvs_two_sensors_each import SETUP_CONFIG
```

These forms hide the module context and make later refactoring harder.
