#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys

from vinetrimmer.utils.widevine.device import LocalDevice

"""
Code to convert common folder/file structure to a vinetrimmer WVD.
"""

parser = argparse.ArgumentParser()
parser.add_argument("dirs", metavar="DIR", nargs="+", help="Directory containing device files")
args = parser.parse_args()

configs = []
for d in args.dirs:
    for root, dirs, files in os.walk(d):
        for f in files:
            if f == "wv.json":
                configs.append(os.path.join(root, f))

if not configs:
    print("No wv.json file found in any of the specified directories.")
    sys.exit(1)

for f in configs:
    d = os.path.dirname(f)

    print(f"Generating WVD struct file for {os.path.abspath(d)}...")

    with open(f, encoding="utf-8") as fd:
        config = json.load(fd)

    device = LocalDevice.from_dir(d)

    # we cannot output to /data/CDM_Devices etc. as the CWD might not align up
    # also best to keep the security level and system id definition on the filename for easy referencing
    name = re.sub(r"_lvl\d$", "", config["name"])
    out_path = f"{name}_l{device.security_level}_{device.system_id}.wvd"

    device.dump(out_path)

    print(device)

    print(f"Done, saved to: {os.path.abspath(out_path)}")
    print()
