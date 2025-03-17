#!/usr/bin/env python3

import argparse

from vinetrimmer.utils.widevine.keybox import Keybox

parser = argparse.ArgumentParser(
    "Keybox parser",
    description="Simple script to read a keybox to see information about it"
)
parser.add_argument(
    "-k", "--keybox",
    help="keybox path",
    required=True)
args = parser.parse_args()

keybox = Keybox.load(args.keybox)
print(repr(keybox))
