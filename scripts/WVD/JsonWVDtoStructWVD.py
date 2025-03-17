#!/usr/bin/env python3

import argparse
import base64
import json
import os

from vinetrimmer.utils.widevine.device import LocalDevice

"""
Code to convert common folder/file structure to a vinetrimmer WVD.
"""

parser = argparse.ArgumentParser(
    "JsonWVDtoStructWVD",
    description="Simple script to read cdm data from old wvd json and write it into a new WVD struct file."
)
parser.add_argument(
    "-i", "--input",
    help="path to wvd json file",
    required=False)
parser.add_argument(
    "-d", "--dir",
    help="path to MULTIPLE wvd json files",
    required=False)
args = parser.parse_args()

files = []
if args.dir:
    files.extend(os.listdir(args.dir))
elif args.input:
    files.append(args.input)

for file in files:
    if not file.lower().endswith(".wvd") or os.path.splitext(file)[0].endswith(".struct"):
        continue

    if not os.path.isfile(file):
        raise ValueError("Not a file or doesn't exist...")

    print(f"Generating wvd struct file for {file}...")

    with open(file, encoding="utf-8") as fd:
        wvd_json = json.load(fd)

    device = LocalDevice(
        type=LocalDevice.Types[wvd_json["device_type"].upper()],
        security_level=wvd_json["security_level"],
        flags={
            "send_key_control_nonce": wvd_json["send_key_control_nonce"]
        },
        private_key=base64.b64decode(wvd_json["device_private_key"]),
        client_id=base64.b64decode(wvd_json["device_client_id_blob"]),
        vmp=base64.b64decode(wvd_json["device_vmp_blob"]) if wvd_json.get("device_vmp_blob") else None
    )

    out = os.path.join(os.path.dirname(file), "structs", os.path.basename(file))
    os.makedirs(os.path.dirname(out), exist_ok=True)

    device.dump(out)

    print(device)
    print(f"Done: {file}")

print("Done")
