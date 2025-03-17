#!/usr/bin/env python3

import argparse
import json
import os

import toml
import yaml

parser = argparse.ArgumentParser()
parser.add_argument("path", help="directory containing .toml files to convert")
args = parser.parse_args()

for root, dirs, files in os.walk(args.path):
    for f in files:
        if f.endswith(".toml"):
            data = toml.load(os.path.join(root, f))
            # Convert to a real dict instead of weird toml object that pyyaml can't handle
            data = json.loads(json.dumps(data))
            with open(os.path.join(root, f"{os.path.splitext(f)[0]}.yml"), "w") as fd:
                print(f"Writing {os.path.realpath(fd.name)}")
                fd.write(yaml.safe_dump(data, sort_keys=False))
