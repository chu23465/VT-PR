#!/usr/bin/env python3

import re
import sys

import requests
from Cryptodome.Cipher import AES

# create a session with a user agent
http = requests.Session()
http.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:68.0) Gecko/20100101 Firefox/68.0"
})
# get player fragment page
fragment = http.get(sys.argv[1].replace("/videos/", "/player5_fragment/")).text
# get encrypted manifest urls for both hls and dash
encrypted_manifests = {k: bytes.fromhex(re.findall(
    r'<source\s+type="application/' + v + r'"\s+src=".+?/e-stream-url\?stream=(.+?)"',
    fragment
)[0][0]) for k, v in {"hls": "x-mpegURL", "dash": r"dash\+xml"}.items()}

# decrypt all manifest urls in manifests
m = re.search(r"^\s*chabi:\s*'(.+?)'", fragment, re.MULTILINE)
if not m:
    raise ValueError("Unable to get key")
key = m.group(1).encode()

m = re.search(r"^\s*ecta:\s*'(.+?)'", fragment, re.MULTILINE)
if not m:
    raise ValueError("Unable to get key")
iv = m.group(1).encode()

manifests = {k: AES.new(key, AES.MODE_CBC, iv).decrypt(v).decode("utf-8") for k, v in encrypted_manifests.items()}
# print em out
print(manifests)
