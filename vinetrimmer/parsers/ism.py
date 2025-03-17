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
from vinetrimmer.utils.io import aria2c
from vinetrimmer.vendor.pymp4.parser import Box

# A stream from ISM is always in fragments
# Example fragment URL
# https://test.playready.microsoft.com/media/profficialsite/tearsofsteel_4k.ism.smoothstreaming/QualityLevels(128003)/Fragments(aac_UND_2_128=0)
# based on https://github.com/SASUKE-DUCK/pywks/blob/dba8a83a0722221bd8d3e53d624b91050b46cfde/cdm/wks.py#L722
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

	ism = xmltodict.parse(data)
	if not ism["SmoothStreamingMedia"]:
		raise ValueError("Non-ISM document provided to Tracks.from_ism")

	encrypted = \
	( True if ism['SmoothStreamingMedia']['Protection']['ProtectionHeader']['@SystemID']
		and
		   ism['SmoothStreamingMedia']['Protection']['ProtectionHeader']['@SystemID'].replace("-", "").upper()
		   in ["9A04F07998404286AB92E65BE0885F95", 'EDEF8BA979D64ACEA3C827DCD51D21ED']
		else False
	)
	pssh = ism['SmoothStreamingMedia']['Protection']['ProtectionHeader']['#text']
	pr_pssh_dec = base64.b64decode(pssh).decode('utf16')
	pr_pssh_dec = pr_pssh_dec[pr_pssh_dec.index('<'):]
	pr_pssh_xml = xmltodict.parse(pr_pssh_dec)
	kid_hex = base64.b64decode(pr_pssh_xml['WRMHEADER']['DATA']['KID']).hex()
	kid = uuid.UUID(kid_hex).bytes_le

	stream_indices = ism['SmoothStreamingMedia']['StreamIndex']

	assert int(ism['SmoothStreamingMedia'].get('@Duration'))
	assert int(ism['SmoothStreamingMedia'].get('@TimeScale'))

	# Seconds
	duration = int(ism['SmoothStreamingMedia'].get('@Duration')) / int(ism['SmoothStreamingMedia'].get('@TimeScale'))

	# List to store information for each stream
	tracks = []

	# Iterate over each StreamIndex (as it might be a list)
	for stream_info in stream_indices if isinstance(stream_indices, list) else [stream_indices]:

		# For some reason Chunks will be roughly equal to int of half of duration in seconds
		#chunks_calc = int(duration / 2)
		#chunks = stream_info['@Chunks']
		#if chunks != chunks_calc:
		#	log.warn(f"{chunks} number of fragments is not equal to calculated number of fragments {chunks_calc}")


		type_info = stream_info['@Type']

		
		# Handle the case where there can be multiple QualityLevel elements
		quality_levels = stream_info.get('QualityLevel', [])
		if not isinstance(quality_levels, list):
			quality_levels = [quality_levels]

		for quality_level in quality_levels:
			fourCC = quality_level.get('@FourCC', 'N/A')
			bitrate = int ( quality_level.get('@Bitrate', 'N/A') ) # Bytes per second

			global max_width
			global max_height
			# Additional attributes for video streams
			if type_info == 'video':
				max_width = quality_level.get('@MaxWidth', 'N/A')
				max_height = quality_level.get('@MaxHeight', 'N/A')
				resolution = f"{max_width}x{max_height}"
			else:
				resolution = 'N/A'

			privateData = quality_level.get('@CodecPrivateData', 'N/A').strip()
			if privateData == "N/A" or privateData == "":
				privateData = None
				#privateData = GenCodecPrivateDataForAAC()

			if fourCC in ["H264", "X264", "DAVC", "AVC1"]:
				try:
					result = re.compile(r"00000001\d7([0-9a-fA-F]{6})").match(privateData)[1]
					codec = f"avc1.{result}"
				except:
					codec = "avc1.4D401E"
			elif fourCC[:3] == "AAC": # ["AAC", "AACL", "AACH", "AACP"]
				mpProfile = 2
				if fourCC == "AACH": 
					mpProfile = 5 # High Efficiency AAC Profile
				elif privateData != "N/A" or privateData != "":
					mpProfile = (int(privateData[:2], 16) & 0xF8) >> 3
					if mpProfile == 0: mpProfile = 2 # Return default audio codec
				codec = f"mp4a.40.{mpProfile}"
			else:
				codec = fourCC
					
			# Additional attributes for audio streams
			lang = stream_info.get('@Language', 'N/A').strip()
			
			try:
				lang = Language.get(lang.split("-")[0])
			except:
				lang = Language.get("und")
				
			audio_id = stream_info.get('@AudioTrackId', 'N/A')

			track_id = "{codec}-{lang}-{bitrate}-{extra}".format(
				codec=codec,
				lang=lang,
				bitrate=bitrate or 0,  # subs may not state bandwidth
				extra=(audio_id or "") + (quality_level.get("@Index") or "") + privateData,
			)
			track_id = md5(track_id.encode()).hexdigest()

			url_template: str = stream_info.get("@Url").replace("{bitrate}", f"{bitrate}").replace("{start time}", "0")
			init_url = url.replace("manifest", url_template)
			#init = (session or requests).get(init_url).text
				# if pssh:
					# pssh = base64.b64decode(pssh)
					# # noinspection PyBroadException
					# try:
						# pssh = Box.parse(pssh)
						
					# except Exception:
						# pssh = Box.parse(Box.build(dict(
							# type=b"pssh",
							# version=0,  # can only assume version & flag are 0
							# flags=0,
							# system_ID=Cdm.uuid,
							# init_data=pssh
						# )))
			if type_info == 'video':
				tracks.append(VideoTrack(
					id_=track_id,
					source=source,
					url=url,
					# metadata
					codec=(codec or "").split(".")[0],
					language=lang,
					bitrate=bitrate,
					width=max_width,
					height=max_height,
					fps=None,
					hdr10=codec and codec[0:4] in ("hvc1", "hev1"), # and codec[5] == 2, # hevc.2XXXXX or hvc1.2XXXXX Needs the hevc full codec script translated from Nm3u8
					hlg=False,
					dv=codec and codec[0:4] in ("dvhe", "dvh1"),
					# switches/options
					descriptor=Track.Descriptor.ISM,
					# decryption
					needs_repack=True, # Necessary
					encrypted=encrypted,
					pssh=pssh,
					kid=kid,
					# extra
					extra=(list(quality_level), list(stream_info),) # Either set size as a attribute of VideoTrack or append to extra here.
				))
			elif type_info == 'audio':
				atmos = ( str( quality_level.get('@HasAtmos', 'N/A') ).lower() == "true" ) or ( "ATM" in stream_info.get('@Name', 'N/A') )
				tracks.append(AudioTrack(
					id_=track_id,
					source=source,
					url=url,
					# metadata
					codec=(codec or "").split(".")[0],
					language=lang,
					bitrate=bitrate,
					channels=quality_level.get('@Channels', 'N/A'),
					atmos=atmos,
					# switches/options
					descriptor=Track.Descriptor.ISM,
					# decryption
					needs_repack=False, # Necessary
					encrypted=encrypted,
					pssh=pssh,
					kid=kid,
					# extra
					extra=(dict(quality_level), dict(stream_info),)
				))
	return tracks
