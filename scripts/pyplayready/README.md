# pyplayready
All of this is already public. 100% of this code has been derived from the mspr_toolkit.

## Installation
```shell
pip install pyplayready
```

Run `pyplayready --help` to view available cli functions

## Devices
Run the command below to create a Playready Device (.prd) from a `bgroupcert.dat` and `zgpriv.dat`:
```shell
pyplayready create-device -c bgroupcert.dat -k zgpriv.dat
```

Test a playready device:
```shell
pyplayready test DEVICE.prd
```

> [!IMPORTANT]  
> There currently isn't a proper method of extracting Group Certificates/Keys. They can be found inside older Samsung phones/Smart TVs, Windows DLLs and set-top-boxes in encrypted form.

Export a provisioned device to its raw .dat files
```shell
pyplayready export-device DEVICE.prd
```

## Usage
An example code snippet:

```python
from pyplayready.cdm import Cdm
from pyplayready.device import Device
from pyplayready.system.pssh import PSSH

import requests

device = Device.load("C:/Path/To/A/Device.prd")
cdm = Cdm.from_device(device)
session_id = cdm.open()

pssh = PSSH(
    "AAADfHBzc2gAAAAAmgTweZhAQoarkuZb4IhflQAAA1xcAwAAAQABAFIDPABXAFIATQBIAEUAQQBEAEUAUgAgAHgAbQBsAG4AcwA9ACIAaAB0AH"
    "QAcAA6AC8ALwBzAGMAaABlAG0AYQBzAC4AbQBpAGMAcgBvAHMAbwBmAHQALgBjAG8AbQAvAEQAUgBNAC8AMgAwADAANwAvADAAMwAvAFAAbABh"
    "AHkAUgBlAGEAZAB5AEgAZQBhAGQAZQByACIAIAB2AGUAcgBzAGkAbwBuAD0AIgA0AC4AMAAuADAALgAwACIAPgA8AEQAQQBUAEEAPgA8AFAAUg"
    "BPAFQARQBDAFQASQBOAEYATwA+ADwASwBFAFkATABFAE4APgAxADYAPAAvAEsARQBZAEwARQBOAD4APABBAEwARwBJAEQAPgBBAEUAUwBDAFQA"
    "UgA8AC8AQQBMAEcASQBEAD4APAAvAFAAUgBPAFQARQBDAFQASQBOAEYATwA+ADwASwBJAEQAPgA0AFIAcABsAGIAKwBUAGIATgBFAFMAOAB0AE"
    "cAawBOAEYAVwBUAEUASABBAD0APQA8AC8ASwBJAEQAPgA8AEMASABFAEMASwBTAFUATQA+AEsATABqADMAUQB6AFEAUAAvAE4AQQA9ADwALwBD"
    "AEgARQBDAEsAUwBVAE0APgA8AEwAQQBfAFUAUgBMAD4AaAB0AHQAcABzADoALwAvAHAAcgBvAGYAZgBpAGMAaQBhAGwAcwBpAHQAZQAuAGsAZQ"
    "B5AGQAZQBsAGkAdgBlAHIAeQAuAG0AZQBkAGkAYQBzAGUAcgB2AGkAYwBlAHMALgB3AGkAbgBkAG8AdwBzAC4AbgBlAHQALwBQAGwAYQB5AFIA"
    "ZQBhAGQAeQAvADwALwBMAEEAXwBVAFIATAA+ADwAQwBVAFMAVABPAE0AQQBUAFQAUgBJAEIAVQBUAEUAUwA+ADwASQBJAFMAXwBEAFIATQBfAF"
    "YARQBSAFMASQBPAE4APgA4AC4AMQAuADIAMwAwADQALgAzADEAPAAvAEkASQBTAF8ARABSAE0AXwBWAEUAUgBTAEkATwBOAD4APAAvAEMAVQBT"
    "AFQATwBNAEEAVABUAFIASQBCAFUAVABFAFMAPgA8AC8ARABBAFQAQQA+ADwALwBXAFIATQBIAEUAQQBEAEUAUgA+AA=="
)

wrm_headers = pssh.get_wrm_headers()
request = cdm.get_license_challenge(session_id, wrm_headers[0])

response = requests.post(
    url="https://test.playready.microsoft.com/service/rightsmanager.asmx?cfg=(persist:false,sl:2000)",
    headers={
        'Content-Type': 'text/xml; charset=UTF-8',
    },
    data=request,
)

cdm.parse_license(session_id, response.text)

for key in cdm.get_keys(session_id):
    print(f"{key.key_id.hex}:{key.key.hex()}")

cdm.close(session_id)
```

## Disclaimer

1. This project requires a valid Microsoft Certificate and Group Key, which are not provided by this project.
2. Public test provisions are available and provided by Microsoft to use for testing projects such as this one.
3. This project does not condone piracy or any action against the terms of the DRM systems.
4. All efforts in this project have been the result of Reverse-Engineering, Publicly available research, and Trial & Error.
5. Do not use this program to decrypt or access any content for which you do not have the legal rights or explicit permission.
6. Unauthorized decryption or distribution of copyrighted materials is a violation of applicable laws and intellectual property rights.
7. This tool must not be used for any illegal activities, including but not limited to piracy, circumventing digital rights management (DRM), or unauthorized access to protected content.
8. The developers, contributors, and maintainers of this program are not responsible for any misuse or illegal activities performed using this software.
9. By using this program, you agree to comply with all applicable laws and regulations governing digital rights and copyright protections.

## Credits
+ [mspr_toolkit](https://security-explorations.com/materials/mspr_toolkit.zip)
