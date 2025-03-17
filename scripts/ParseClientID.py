#!/usr/bin/env python3

import argparse

from vinetrimmer.utils.widevine.device import LocalDevice
from vinetrimmer.utils.widevine.protos.widevine_pb2 import ClientIdentification

parser = argparse.ArgumentParser(
    "Client identification parser",
    description="Simple script to read a client id blob to see information about it"
)
parser.add_argument(
    "input",
    help="client id blob bin path or path to a wvd file",
)
args = parser.parse_args()

client_id = ClientIdentification()
is_wvd = args.input.lower().endswith(".wvd")

with open(args.input, "rb") as fd:
    data = fd.read()

if is_wvd:
    client_id = LocalDevice.load(data).client_id
else:
    client_id.ParseFromString(data)

print(client_id)
