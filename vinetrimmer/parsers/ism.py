import xmltodict
import asyncio
import base64
import json
import math
import os
import re
import urllib.parse
import uuid
from copy import copy
from hashlib import md5

import requests
from langcodes import Language
from langcodes.tag_parser import LanguageTagError

from vinetrimmer import config
from vinetrimmer.objects import AudioTrack, TextTrack, Track, Tracks, VideoTrack
from vinetrimmer.utils import Cdm
from vinetrimmer.utils.io import aria2c
from vinetrimmer.utils.xml import load_xml
from vinetrimmer.vendor.pymp4.parser import Box


def parse(*, url=None, data=None, source, session=None, downloader=None):
	"""
	Convert an Smooth Streaming ISM (IIS Smooth Streaming Manifest) document to a Tracks object
	with video, audio and subtitle track objects where available.

	:param url: URL of the ISM document.
	:param data: The ISM document as a string.
	:param source: Source tag for the returned tracks.
	:param session: Used for any remote calls, e.g. getting the MPD document from an URL.
		Can be useful for setting custom headers, proxies, etc.
	:param downloader: Downloader to use. Accepted values are None (use requests to download)
		and aria2c.

	Don't forget to manually handle the addition of any needed or extra information or values
	like `encrypted`, `pssh`, `hdr10`, `dv`, etc. Essentially anything that is per-service
	should be looked at. Some of these values like `pssh` will be attempted to be set automatically
	if possible but if you definitely have the values in the service, then set them.

	Examples:
		url = "https://test.playready.microsoft.com/media/profficialsite/tearsofsteel_4k.ism.smoothstreaming/manifest" # https://testweb.playready.microsoft.com/Content/Content2X
		session = requests.Session(headers={"X-Example": "foo"})
		tracks = Tracks.from_ism(
			url,
			session=session,
			source="MICROSOFT",
		)

		url = "https://test.playready.microsoft.com/media/profficialsite/tearsofsteel_4k.ism.smoothstreaming/manifest"
		session = requests.Session(headers={"X-Example": "foo"})
		tracks = Tracks.from_ism(url=url, data=session.get(url).text, source="MICROSOFT")
	"""
	tracks = []
	if not data:
		if not url:
			raise ValueError("Neither a URL nor a document was provided to Tracks.from_ism")
		base_url = url.rsplit('/', 1)[0] + '/'
		if downloader is None:
			data = (session or requests).get(url).text
		elif downloader == "aria2c":
			out = os.path.join(config.directories.temp, url.split("/")[-1])
			asyncio.run(aria2c(url, out))

			with open(out, encoding="utf-8") as fd:
				data = fd.read()

			try:
				os.unlink(out)
			except FileNotFoundError:
				pass
		else:
			raise ValueError(f"Unsupported downloader: {downloader}")

	root = load_xml(data)
	if root.tag != "SmoothStreamingMedia":
		raise ValueError("Non-ISM document provided to Tracks.from_ism")
