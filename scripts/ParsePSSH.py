#!/usr/bin/env python3

import argparse
import base64

from vinetrimmer.utils.widevine.protos.widevine_pb2 import WidevineCencHeader
from vinetrimmer.vendor.pymp4.parser import Box

parser = argparse.ArgumentParser(
    "PSSH parser",
    description="Simple script to read a PSSH to see information about it"
)
parser.add_argument(
    "input",
)
args = parser.parse_args()

args.input = base64.b64decode(args.input.encode("utf-8"))
box = Box.parse(args.input)
cenc_header = WidevineCencHeader()
cenc_header.ParseFromString(box.init_data)

print("pssh box:")
print(box)

print("init_data parsed as WidevineCencHeader:")
print(cenc_header)

print("init_data's key_id as hex:")
print(cenc_header.key_id[0].hex())
