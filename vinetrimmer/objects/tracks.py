import asyncio
import base64
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections import defaultdict
from enum import Enum
from io import BytesIO, TextIOWrapper
import humanfriendly
import m3u8
import pycaption
import requests
import pysubs2
from langcodes import Language
from requests import Session
from vinetrimmer import config
from vinetrimmer.constants import LANGUAGE_MUX_MAP, TERRITORY_MAP
from vinetrimmer.utils import Cdm, get_boxes, get_closest_match, is_close_match, try_get
from vinetrimmer.utils.collections import as_list
from vinetrimmer.utils.io import aria2c, download_range, saldl
from vinetrimmer.utils.subprocess import ffprobe
from vinetrimmer.utils.widevine.protos.widevine_pb2 import WidevineCencHeader
from vinetrimmer.utils.xml import load_xml
from vinetrimmer.vendor.pymp4.parser import Box, MP4

CODEC_MAP = {
    # Video
    "avc1": "H.264",
    "avc3": "H.264",
    "hev1": "H.265",
    "hvc1": "H.265",
    "dvh1": "H.265",
    "dvhe": "H.265",
    # Audio
    "aac": "AAC",
    "mp4a": "AAC",
    "stereo": "AAC",
    "HE": "HE-AAC",
    "ac3": "AC3",
    "ac-3": "AC3",
    "eac": "E-AC3",
    "eac-3": "E-AC3",
    "ec-3": "E-AC3",
    "atmos": "E-AC3",
    # Subtitles
    "srt": "SRT",
    "vtt": "VTT",
    "wvtt": "VTT",
    "dfxp": "TTML",
    "stpp": "TTML",
    "ttml": "TTML",
    "tt": "TTML",
}


class Track:
    class Descriptor(Enum):
        URL = 1  # Direct URL, nothing fancy
        M3U = 2  # https://en.wikipedia.org/wiki/M3U (and M3U8)
        MPD = 3  # https://en.wikipedia.org/wiki/Dynamic_Adaptive_Streaming_over_HTTP

    def __init__(self, id_, source, url, codec, language=None, descriptor=Descriptor.URL,
                 needs_proxy=False, needs_repack=False, encrypted=False, pssh=None, note=None, kid=None, key=None, extra=None):
        self.id = id_
        self.source = source
        self.url = url
        # required basic metadata
        self.note= note
        self.codec = codec
        #self.language = Language.get(language or "none")
        self.language = Language.get(language or "en")
        self.is_original_lang = False  # will be set later
        # optional io metadata
        self.descriptor = descriptor
        self.needs_proxy = bool(needs_proxy)
        self.needs_repack = bool(needs_repack)
        # decryption
        self.encrypted = bool(encrypted)
        self.pssh = pssh
        self.kid = kid
        self.key = key
        # extra data
        self.extra = extra or {}  # allow anything for extra, but default to a dict

        # should only be set internally
        self._location = None

    def __repr__(self):
        return "{name}({items})".format(
            name=self.__class__.__name__,
            items=", ".join([f"{k}={repr(v)}" for k, v in self.__dict__.items()])
        )

    def __eq__(self, other):
        return isinstance(other, Track) and self.id == other.id

    def get_track_name(self):
        """Return the base track name. This may be enhanced in subclasses."""
        if self.language is None:
            self.language = Language.get("en")
        if ((self.language.language or "").lower() == (self.language.territory or "").lower()
                and self.language.territory not in TERRITORY_MAP):
            self.language.territory = None  # e.g. de-DE
        if self.language.territory == "US":
            self.language.territory = None
        language = self.language.simplify_script()
        extra_parts = []
        if language.script is not None:
            extra_parts.append(language.script_name())
        if language.territory is not None:
            territory = language.territory_name()
            extra_parts.append(TERRITORY_MAP.get(language.territory, territory))
        return ", ".join(extra_parts) or None

    def get_data_chunk(self, session=None):
        """Get the data chunk from the track's stream."""
        if not session:
            session = Session()

        url = None

        if self.descriptor == self.Descriptor.M3U:
            master = m3u8.loads(session.get(as_list(self.url)[0]).text, uri=self.url)
            for segment in master.segments:
                if not segment.init_section:
                    continue
                if self.source in ["DSNP", "STRP"] and re.match(r"^[a-zA-Z0-9]{4}-(BUMPER|DUB_CARD)/", segment.init_section.uri):
                    continue
                url = ("" if re.match("^https?://", segment.init_section.uri) else segment.init_section.base_uri)
                url += segment.init_section.uri
                break

        if not url:
            url = as_list(self.url)[0]

        with session.get(url, stream=True) as s:
            # assuming enough to contain the pssh/kid
            for chunk in s.iter_content(20000):
                # we only want the first chunk
                return chunk

        # assuming 20000 bytes is enough to contain the pssh/kid box
        return download_range(url, 20000, proxy=proxy)

    def get_pssh(self, session=None):
        """
        Get the PSSH of the track.

        Parameters:
            session: Requests Session, best to provide one if cookies/headers/proxies are needed.

        Returns:
            True if PSSH is now available, False otherwise. PSSH will be stored in Track.pssh
            automatically.
        """
        
        if self.pssh or not self.encrypted:
            return True

        if self.descriptor == self.Descriptor.M3U:
            # if an m3u, try get from playlist
            master = m3u8.loads(session.get(as_list(self.url)[0]).text, uri=self.url)
            for x in master.session_keys:
                if x and x.keyformat.lower == "com.microsoft.playready":
                    self.pssh = x.uri.split(",")[-1]
                    break
            for x in master.keys:
                if x and "com.microsoft.playready" in str(x):
                    self.pssh = str(x).split("\"")[1].split(",")[-1]
                    break
        
        try:
            xml_str = base64.b64decode(self.pssh).decode("utf-16-le", "ignore")
            xml_str = xml_str[xml_str.index("<"):]

            xml = load_xml(xml_str).find("DATA")  # root: WRMHEADER

            self.kid = xml.findtext("KID")  # v4.0.0.0
            if not self.kid:  # v4.1.0.0
                self.kid = next(iter(xml.xpath("PROTECTINFO/KID/@VALUE")), None)
            if not self.kid:  # v4.3.0.0
                self.kid = next(iter(xml.xpath("PROTECTINFO/KIDS/KID/@VALUE")), None)  # can be multiple?

            self.kid = uuid.UUID(base64.b64decode(self.kid).hex()).bytes_le.hex()
            
            return True

        except: pass

        # boxes = []

        # if self.descriptor == self.Descriptor.M3U:
            # # if an m3u, try get from playlist
            # master = m3u8.loads(session.get(as_list(self.url)[0]).text, uri=self.url)
            # boxes.extend([
                # Box.parse(base64.b64decode(x.uri.split(",")[-1]))
                # for x in (master.session_keys or master.keys)
                # if x and x.keyformat.lower() == Cdm.urn
            # ])

        # data = self.get_data_chunk(session)
        # if data:
            # boxes.extend(list(get_boxes(data, b"pssh")))

        # for box in boxes:
            # if box.system_ID == Cdm.uuid:
                # print(box.system_ID)
                # self.pssh = box
                # return True

        # for box in boxes:
            # if box.system_ID == uuid.UUID("{9a04f079-9840-4286-ab92-e65be0885f95}"):
                # xml_str = Box.build(box)
                # xml_str = xml_str.decode("utf-16-le", "ignore")
                # xml_str = xml_str[xml_str.index("<"):]

                # xml = load_xml(xml_str).find("DATA")  # root: WRMHEADER

                # kid = xml.findtext("KID")  # v4.0.0.0
                # if not kid:  # v4.1.0.0
                    # kid = next(iter(xml.xpath("PROTECTINFO/KID/@VALUE")), None)
                # if not kid:  # v4.3.0.0
                    # kid = next(iter(xml.xpath("PROTECTINFO/KIDS/KID/@VALUE")), None)  # can be multiple?

                # # self.pssh = Box.parse(Box.build(dict(
                    # # type=b"pssh",
                    # # version=0,
                    # # flags=0,
                    # # system_ID="9a04f079-9840-4286-ab92-e65be0885f95",
                    # # init_data=b"\x12\x10" + base64.b64decode(kid)
                # # )))
                # return True

        return False

    def get_kid(self, session=None):
        """
        Get the KID (encryption key id) of the Track.
        The KID corresponds to the Encrypted segments of an encrypted Track.

        Parameters:
            session: Requests Session, best to provide one if cookies/headers/proxies are needed.

        Returns:
            True if KID is now available, False otherwise. KID will be stored in Track.kid
            automatically.
        """
        
        try:
            xml_str = base64.b64decode(self.pssh).decode("utf-16-le", "ignore")
            xml_str = xml_str[xml_str.index("<"):]

            xml = load_xml(xml_str).find("DATA")  # root: WRMHEADER

            self.kid = xml.findtext("KID")  # v4.0.0.0
            if not self.kid:  # v4.1.0.0
                self.kid = next(iter(xml.xpath("PROTECTINFO/KID/@VALUE")), None)
            if not self.kid:  # v4.3.0.0
                self.kid = next(iter(xml.xpath("PROTECTINFO/KIDS/KID/@VALUE")), None)  # can be multiple?

            self.kid = uuid.UUID(base64.b64decode(self.kid).hex()).bytes_le.hex()

        except: pass
        
        if self.kid or not self.encrypted:
            return True

        # boxes = []

        # data = self.get_data_chunk(session)

        # if data:
            # # try get via ffprobe, needed for non mp4 data e.g. WEBM from Google Play
            # probe = ffprobe(data)
            # if probe:
                # kid = try_get(probe, lambda x: x["streams"]["tags"]["enc_key_id"])
                # if kid:
                    # kid = base64.b64decode(kid).hex()
                    # if kid != "00" * 16:
                        # self.kid = kid
                        # return True
            # # get tenc and pssh boxes if available
            # boxes.extend(list(get_boxes(data, b"tenc")))
            # boxes.extend(list(get_boxes(data, b"pssh")))

        # # get the track's pssh box if available
        # if self.get_pssh():
            # boxes.append(self.pssh)

        # # loop all found boxes and try find a KID
        # for box in sorted(boxes, key=lambda b: b.type == b"tenc", reverse=True):
            # if box.type == b"tenc":
                # kid = box.key_ID.hex
                # if kid != "00" * 16:
                    # self.kid = kid
                    # return True
            # if box.type == b"pssh":
                # if box.system_ID == Cdm.uuid:
                    # # Note: assumes only the first KID of a list is wanted
                    # if getattr(box, "key_IDs", None):
                        # kid = box.key_IDs[0].hex
                        # if kid != "00" * 16:
                            # self.kid = kid
                            # return True
                    # cenc_header = WidevineCencHeader()
                    # cenc_header.ParseFromString(box.init_data)
                    # if getattr(cenc_header, "key_id", None):
                        # kid = cenc_header.key_id[0]
                        # try:
                            # int(kid, 16)  # KID may be already hex
                        # except ValueError:
                            # kid = kid.hex()
                        # else:
                            # kid = kid.decode()
                        # if kid != "00" * 16:
                            # self.kid = kid
                            # return True

        return False

    def download(self, out, name=None, headers=None, proxy=None):
        """
        Download the Track and apply any necessary post-edits like Subtitle conversion.

        Parameters:
            out: Output Directory Path for the downloaded track.
            name: Override the default filename format.
                Expects to contain `{type}`, `{id}`, and `{enc}`. All of them must be used.
            headers: Headers to use when downloading.
            proxy: Proxy to use when downloading.

        Returns:
            Where the file was saved.
        """
        if os.path.isfile(out):
            raise ValueError("Path must be to a directory and not a file")

        os.makedirs(out, exist_ok=True)

        name = (name or "{type}_{id}_{enc}").format(
            type=self.__class__.__name__,
            id=self.id,
            enc="enc" if self.encrypted else "dec"
        ) + ".mp4"
        save_path = os.path.join(out, name)

        if self.descriptor == self.Descriptor.M3U:
            master = m3u8.loads(
                requests.get(
                    as_list(self.url)[0],
                    headers=headers,
                    proxies={"all": proxy} if self.needs_proxy and proxy else None
                ).text,
                uri=as_list(self.url)[0]
            )

            # Keys may be [] or [None] if unencrypted
            if any(master.keys + master.session_keys):
                self.encrypted = True
                self.get_kid()
                self.get_pssh()

            durations = []
            duration = 0
            for segment in master.segments:
                if segment.discontinuity:
                    durations.append(duration)
                    duration = 0
                duration += segment.duration
            durations.append(duration)
            largest_continuity = durations.index(max(durations))

            discontinuity = 0
            has_init = False
            segments = []
            for segment in master.segments:
                if segment.discontinuity:
                    discontinuity += 1
                    has_init = False
                if self.source in ["DSNP", "STRP"] and re.search(
                    r"[a-zA-Z0-9]{4}-(BUMPER|DUB_CARD)/",
                    segment.uri + (segment.init_section.uri if segment.init_section else '')
                ):
                    continue
                if self.source == "ATVP" and discontinuity != largest_continuity:
                    # the amount of pre and post-roll sections change all the time
                    # only way to know which section to get is by getting the largest
                    continue
                if segment.init_section and not has_init:
                    segments.append(
                        ("" if re.match("^https?://", segment.init_section.uri) else segment.init_section.base_uri) +
                        segment.init_section.uri
                    )
                    has_init = True
                segments.append(
                    ("" if re.match("^https?://", segment.uri) else segment.base_uri) +
                    segment.uri
                )
            self.url = segments

        if self.source == "CORE":
            asyncio.run(saldl(
                self.url,
                save_path,
                headers,
                proxy if self.needs_proxy else None
            ))
        else:
            try:
                asyncio.run(aria2c(
                    self.url,
                    save_path,
                    headers,
                    proxy if self.needs_proxy else None
                ))
            except:
                asyncio.run(aria2c(
                    self.url,
                    save_path,
                    headers,
                    proxy if self.needs_proxy else None
                ))

        if os.stat(save_path).st_size <= 3:  # Empty UTF-8 BOM == 3 bytes
            raise IOError(
                "Download failed, the downloaded file is empty. "
                f"This {'was' if self.needs_proxy else 'was not'} downloaded with a proxy." +
                (
                    " Perhaps you need to set `needs_proxy` as True to use the proxy for this track."
                    if not self.needs_proxy else ""
                )
            )

        self._location = save_path
        return save_path

    def delete(self):
        if self._location:
            os.unlink(self._location)
            self._location = None

    def repackage(self):
        if not self._location:
            raise ValueError("Cannot repackage a Track that has not been downloaded.")
        fixed_file = f"{self._location}_fixed.mkv"
        try:
            subprocess.run([
                "ffmpeg", "-hide_banner",
                "-loglevel", "panic",
                "-i", self._location,
                # Following are very important!
                "-map_metadata", "-1",  # don't transfer metadata to output file
                "-fflags", "bitexact",  # only have minimal tag data, reproducible mux
                "-codec", "copy",
                fixed_file
            ], check=True)
            self.swap(fixed_file)
        except subprocess.CalledProcessError:
            pass

    def locate(self):
        return self._location

    def move(self, target):
        if not self._location:
            return False
        ok = os.path.realpath(shutil.move(self._location, target)) == os.path.realpath(target)
        if ok:
            self._location = target
        return ok

    def swap(self, target):
        if not os.path.exists(target) or not self._location:
            return False
        os.unlink(self._location)
        os.rename(target, self._location)
        return True

    @staticmethod
    def pt_to_sec(d):
        if isinstance(d, float):
            return d
        if d[0:2] == "P0":
            d = d.replace("P0Y0M0DT", "PT")
        if d[0:2] != "PT":
            raise ValueError("Input data is not a valid time string.")
        d = d[2:].upper()  # skip `PT`
        m = re.findall(r"([\d.]+.)", d)
        return sum(
            float(x[0:-1]) * {"H": 60 * 60, "M": 60, "S": 1}[x[-1].upper()]
            for x in m
        )


class VideoTrack(Track):
    def __init__(self, *args, bitrate, width, size=None, height, fps=None, hdr10=False, hlg=False, dv=False,
                 needs_ccextractor=False, needs_ccextractor_first=False, **kwargs):                 
        super().__init__(*args, **kwargs)
        # required
        self.bitrate = int(math.ceil(float(bitrate))) if bitrate else None
        self.width = int(width)
        self.height = int(height)
        # optional
        if "/" in str(fps):
            num, den = fps.split("/")
            self.fps = int(num) / int(den)
        elif fps:
            self.fps = float(fps)
        else:
            self.fps = None
        self.size = size if size else None
        self.hdr10 = bool(hdr10)
        self.hlg = bool(hlg)
        self.dv = bool(dv)
        self.needs_ccextractor = needs_ccextractor
        self.needs_ccextractor_first = needs_ccextractor_first

    def __str__(self):
        codec = next((CODEC_MAP[x] for x in CODEC_MAP if (self.codec or "").startswith(x)), self.codec)
        fps = f"{self.fps:.3f}" if self.fps else "Unknown"
        size =  f" ({humanfriendly.format_size(self.size, binary=True)})" if self.size else ""
        return " | ".join([
            "├─ VID",
            f"[{codec}, {'HDR10' if self.hdr10 else 'HLG' if self.hlg else 'DV' if self.dv else 'SDR'}]",
            f"{self.width}x{self.height} @ {self.bitrate // 1000 if self.bitrate else '?'} kb/s{size}, {fps} FPS"
        ])

    def ccextractor(self, track_id, out_path, language, original=False):
        """Return a TextTrack object representing CC track extracted by CCExtractor."""
        if not self._location:
            raise ValueError("You must download the track first.")

        executable = shutil.which("ccextractor") or shutil.which("ccextractorwin")
        if not executable:
            raise EnvironmentError("ccextractor executable was not found.")

        p = subprocess.Popen([
            executable,
            "-quiet", "-trim", "-noru", "-ru1",
            self._location, "-o", out_path
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in TextIOWrapper(p.stdout, encoding="utf-8"):
            if "[iso file] Unknown box type ID32" not in line:
                sys.stdout.write(line)
        returncode = p.wait()
        if returncode and returncode != 10:
            raise self.log.exit(f" - ccextractor exited with return code {returncode}")

        if os.path.exists(out_path):
            if os.stat(out_path).st_size <= 3:
                # An empty UTF-8 file with BOM is 3 bytes.
                # If the subtitle file is empty, mkvmerge will fail to mux.
                os.unlink(out_path)
                return None
            cc_track = TextTrack(
                id_=track_id,
                source=self.source,
                url="",  # doesn't need to be downloaded
                codec="srt",
                language=language,
                #is_original_lang=original,  # TODO: Figure out if this is the original title language
                cc=True
            )
            cc_track._location = out_path
            return cc_track

        return None


class AudioTrack(Track):
    #def __init__(self, *args, bitrate, channels=None, descriptive=False, **kwargs):
    def __init__(self, *args, bitrate, size=None, channels=None,
                 descriptive: bool = False, atmos: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        # required
        self.bitrate = int(math.ceil(float(bitrate))) if bitrate else None
        self.size = size if size else None
        self.channels = self.parse_channels(channels) if channels else None
        self.atmos = bool(atmos)
        # optional
        self.descriptive = bool(descriptive)

    @staticmethod
    def parse_channels(channels):
        """
        Converts a string to a float-like string which represents audio channels.
        E.g. "2" -> "2.0", "6" -> "5.1".
        """
        # TODO: Support all possible DASH channel configurations (https://datatracker.ietf.org/doc/html/rfc8216)
        if channels == "A000":
            return "2.0"
        if channels == "F801":
            return "5.1"

        try:
            channels = str(float(channels))
        except ValueError:
            channels = str(channels)

        if channels == "6.0":
            return "5.1"

        return channels

    def get_track_name(self):
        """Return the base Track Name."""
        track_name = super().get_track_name() or ""
        flag = self.descriptive and "Descriptive"
        if flag:
            if track_name:
                flag = f" ({flag})"
            track_name += flag
        return track_name or None

    def __str__(self):
        size =  f" ({humanfriendly.format_size(self.size, binary=True)})" if self.size else ""
        codec = next((CODEC_MAP[x] for x in CODEC_MAP if (self.codec or "").startswith(x)), self.codec)
        return " | ".join([x for x in [
            "├─ AUD",
            f"[{codec}]",
            f"[{self.codec}{', atmos' if self.atmos else ''}]",
            f"{self.channels}" if self.channels else None,
            f"{self.bitrate // 1000 if self.bitrate else '?'} kb/s{size}",
            f"{self.language}",
            " ".join([self.get_track_name() or "", "[Original]" if self.is_original_lang else ""]).strip()
        ] if x])


class TextTrack(Track):
    def __init__(self, *args, cc=False, sdh=False, forced=False, **kwargs):
        """
        Information on Subtitle Types:
            https://bit.ly/2Oe4fLC (3PlayMedia Blog on SUB vs CC vs SDH).
            However, I wouldn't pay much attention to the claims about SDH needing to
            be in the original source language. It's logically not true.

            CC == Closed Captions. Source: Basically every site.
            SDH = Subtitles for the Deaf or Hard-of-Hearing. Source: Basically every site.
            HOH = Exact same as SDH. Is a term used in the UK. Source: https://bit.ly/2PGJatz (ICO UK)

            More in-depth information, examples, and stuff to look for can be found in the Parameter
            explanation list below.

        Parameters:
            cc: Closed Caption.
                - Intended as if you couldn't hear the audio at all.
                - Can have Sound as well as Dialogue, but doesn't have to.
                - Original source would be from an EIA-CC encoded stream. Typically all
                  upper-case characters.
                Indicators of it being CC without knowing original source:
                  - Extracted with CCExtractor, or
                  - >>> (or similar) being used at the start of some or all lines, or
                  - All text is uppercase or at least the majority, or
                  - Subtitles are Scrolling-text style (one line appears, oldest line
                    then disappears).
                Just because you downloaded it as a SRT or VTT or such, doesn't mean it
                 isn't from an EIA-CC stream. And I wouldn't take the streaming services
                 (CC) as gospel either as they tend to get it wrong too.
            sdh: Deaf or Hard-of-Hearing. Also known as HOH in the UK (EU?).
                 - Intended as if you couldn't hear the audio at all.
                 - MUST have Sound as well as Dialogue to be considered SDH.
                 - It has no "syntax" or "format" but is not transmitted using archaic
                   forms like EIA-CC streams, would be intended for transmission via
                   SubRip (SRT), WebVTT (VTT), TTML, etc.
                 If you can see important audio/sound transcriptions and not just dialogue
                  and it doesn't have the indicators of CC, then it's most likely SDH.
                 If it doesn't have important audio/sounds transcriptions it might just be
                  regular subtitling (you wouldn't mark as CC or SDH). This would be the
                  case for most translation subtitles. Like Anime for example.
            forced: Typically used if there's important information at some point in time
                     like watching Dubbed content and an important Sign or Letter is shown
                     or someone talking in a different language.
                    Forced tracks are recommended by the Matroska Spec to be played if
                     the player's current playback audio language matches a subtitle
                     marked as "forced".
                    However, that doesn't mean every player works like this but there is
                     no other way to reliably work with Forced subtitles where multiple
                     forced subtitles may be in the output file. Just know what to expect
                     with "forced" subtitles.
        """
        super().__init__(*args, **kwargs)
        self.cc = bool(cc)
        self.sdh = bool(sdh)
        if self.cc and self.sdh:
            raise ValueError("A text track cannot be both CC and SDH.")
        self.forced = bool(forced)
        if (self.cc or self.sdh) and self.forced:
            raise ValueError("A text track cannot be CC/SDH as well as Forced.")

    def get_track_name(self):
        """Return the base Track Name."""
        track_name = super().get_track_name() or ""
        flag = self.cc and "CC" or self.sdh and "SDH" or self.forced and "Forced"
        if flag:
            if track_name:
                flag = f" ({flag})"
            track_name += flag
        return track_name or None

    @staticmethod
    def parse(data, codec):
        # TODO: Use an "enum" for subtitle codecs
        if not isinstance(data, bytes):
            raise ValueError(f"Subtitle data must be parsed as bytes data, not {data.__class__.__name__}")
        try:
            if codec.startswith("stpp"):
                captions = defaultdict(list)
                for segment in (
                    TextTrack.parse(box.data, "ttml")
                    for box in MP4.parse_stream(BytesIO(data)) if box.type == b"mdat"
                ):
                    lang = segment.get_languages()[0]
                    for caption in segment.get_captions(lang):
                        prev_caption = captions and captions[lang][-1]

                        if prev_caption and (prev_caption.start, prev_caption.end) == (caption.start, caption.end):
                            # Merge cues with equal start and end timestamps.
                            #
                            # pycaption normally does this itself, but we need to do it manually here
                            # for the next merge to work properly.
                            prev_caption.nodes += [pycaption.CaptionNode.create_break(), *caption.nodes]
                        elif prev_caption and caption.start <= prev_caption.end:
                            # If the previous cue's end timestamp is less or equal to the current cue's start timestamp,
                            # just extend the previous one's end timestamp to the current one's end timestamp.
                            # This is to get rid of duplicates, as STPP may duplicate cues at segment boundaries.
                            prev_caption.end = caption.end
                        else:
                            captions[lang].append(caption)

                return pycaption.CaptionSet(captions)
            if codec in ["dfxp", "ttml", "tt"]:
                text = data.decode("utf-8").replace("tt:", "")
                return pycaption.DFXPReader().read(text)
            if codec in ["vtt", "webvtt", "wvtt"] or codec.startswith("webvtt"):
                text = data.decode("utf-8").replace("\r", "").replace("\n\n\n", "\n \n\n").replace("\n\n<", "\n<")
                text = re.sub(r"&rlm;", "\u202B", text)
                return pycaption.WebVTTReader().read(text)
            if codec.lower() == "ass":
                try:
                    subs = pysubs2.load(data.decode('utf-8'))
                    captions = {}
                    for line in subs:
                        if line.start is not None and line.end is not None and line.text:
                            caption = pycaption.Caption(
                                start=line.start.to_time().total_seconds(),
                                end=line.end.to_time().total_seconds(),
                                nodes=[pycaption.CaptionNode.create_text(line.text)]
                            )
                            if line.style:
                                caption.style = line.style.name  # Optionally include the style name
                            if line.actor:
                                caption.actor = line.actor  # Optionally include the actor name
                            if line.effect:
                                caption.effect = line.effect  # Optionally include the effect
                            captions[line.style.name] = captions.get(line.style.name, []) + [caption]

                    return pycaption.CaptionSet(captions)
                except Exception as e:
                    raise ValueError(f"Failed to parse .ass subtitle: {str(e)}")
        except pycaption.exceptions.CaptionReadSyntaxError:
            raise SyntaxError(f"A syntax error has occurred when reading the \"{codec}\" subtitle")
        except pycaption.exceptions.CaptionReadNoCaptions:
            return pycaption.CaptionSet({"en": []})

        raise ValueError(f"Unknown subtitle format: {codec!r}")

    @staticmethod
    def convert_to_srt(data, codec):
        if isinstance(data, bytes):
            data = data.decode()

        from vinetrimmer.utils.ttml2ssa import Ttml2Ssa
        ttml = Ttml2Ssa()
        if codec in ["dfxp", "ttml", "tt"] or codec.startswith("ttml"):
            ttml.parse_ttml_from_string(data)
        else:  # codec in ["vtt", "webvtt", "wvtt"] or codec.startswith("webvtt"):
            ttml.parse_vtt_from_string(data)

        for entry in ttml.entries:
            text = str(entry['text'])
            line_split = text.splitlines()
            if len(line_split) == 3:
                text = f"{line_split[0]}\n" \
                        f"{line_split[1]} {line_split[2]}"
            if len(line_split) == 4:
                text = f"{line_split[0]} {line_split[1]}\n" \
                        f"{line_split[2]} {line_split[3]}"
            entry['text'] = text
        
        # return pycaption.SRTWriter().write(TextTrack.parse(data, codec))
        return ttml.generate_srt()
        
    @staticmethod  
    def convert_to_srt2(data, codec):       
        return pycaption.SRTWriter().write(TextTrack.parse(data, codec))


    def download(self, out, name=None, headers=None, proxy=None):
        save_path = super().download(out, name, headers, proxy)
        if self.codec.lower() == "ass":
            return save_path  # Return the .ass file as-is without any conversion
        elif self.source == "iP":
            with open(save_path, "r+b") as fd:
                data = fd.read()
                fd.seek(0)
                fd.truncate()
                fd.write(self.convert_to_srt2(data, self.codec).encode("utf-8"))
            self.codec = "srt"
            return save_path
        elif self.codec.lower() != "srt":
            with open(save_path, "r+b") as fd:
                data = fd.read()
                fd.seek(0)
                fd.truncate()
                fd.write(self.convert_to_srt(data, self.codec).encode("utf-8"))
            self.codec = "srt"
        return save_path

    def __str__(self):
        codec = next((CODEC_MAP[x] for x in CODEC_MAP if (self.codec or "").startswith(x)), self.codec)
        return " | ".join([x for x in [
            "├─ SUB",
            f"[{codec}]",
            f"{self.language}",
            " ".join([self.get_track_name() or "", "[Original]" if self.is_original_lang else ""]).strip()
        ] if x])


class MenuTrack:
    line_1 = re.compile(r"^CHAPTER(?P<number>\d+)=(?P<timecode>[\d\\.]+)$")
    line_2 = re.compile(r"^CHAPTER(?P<number>\d+)NAME=(?P<title>[\d\\.]+)$")

    def __init__(self, number, title, timecode):
        self.id = f"chapter-{number}"
        self.number = number
        self.title = title
        if "." not in timecode:
            timecode += ".000"
        self.timecode = timecode

    def __bool__(self):
        return bool(
            self.number and self.number >= 0 and
            self.title and
            self.timecode
        )

    def __repr__(self):
        """
        OGM-based Simple Chapter Format intended for use with MKVToolNix.

        This format is not officially part of the Matroska spec. This was a format
        designed for OGM tools that MKVToolNix has since re-used. More Information:
        https://mkvtoolnix.download/doc/mkvmerge.html#mkvmerge.chapters.simple
        """
        return "CHAPTER{num}={time}\nCHAPTER{num}NAME={name}".format(
            num=f"{self.number:02}",
            time=self.timecode,
            name=self.title
        )

    def __str__(self):
        return " | ".join([
            "├─ CHP",
            f"[{self.number:02}]",
            self.timecode,
            self.title
        ])

    @classmethod
    def loads(cls, data):
        """Load chapter data from a string."""
        lines = [x.strip() for x in data.strip().splitlines(keepends=False)]
        if len(lines) > 2:
            return MenuTrack.loads("\n".join(lines))
        one, two = lines

        one_m = cls.line_1.match(one)
        two_m = cls.line_2.match(two)
        if not one_m or not two_m:
            raise SyntaxError(f"An unexpected syntax error near:\n{one}\n{two}")

        one_str, timecode = one_m.groups()
        two_str, title = two_m.groups()
        one_num, two_num = int(one_str.lstrip("0")), int(two_str.lstrip("0"))

        if one_num != two_num:
            raise SyntaxError(f"The chapter numbers ({one_num},{two_num}) does not match.")
        if not timecode:
            raise SyntaxError("The timecode is missing.")
        if not title:
            raise SyntaxError("The title is missing.")

        return cls(number=one_num, title=title, timecode=timecode)

    @classmethod
    def load(cls, path):
        """Load chapter data from a file."""
        with open(path, encoding="utf-8") as fd:
            return cls.loads(fd.read())

    def dumps(self):
        """Return chapter data as a string."""
        return repr(self)

    def dump(self, path):
        """Write chapter data to a file."""
        with open(path, "w", encoding="utf-8") as fd:
            return fd.write(self.dumps())

    @staticmethod
    def format_duration(seconds):
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02.0f}:{minutes:02.0f}:{seconds:06.3f}"


class Tracks:
    """
    Tracks.
    Stores video, audio, and subtitle tracks. It also stores chapter/menu entries.
    It provides convenience functions for listing, sorting, and selecting tracks.
    """

    TRACK_ORDER_MAP = {
        VideoTrack: 0,
        AudioTrack: 1,
        TextTrack: 2,
        MenuTrack: 3
    }

    def __init__(self, *args):
        self.videos = []
        self.audios = []
        self.subtitles = []
        self.chapters = []

        if args:
            self.add(as_list(*args))

    def __iter__(self):
        return iter(as_list(self.videos, self.audios, self.subtitles))

    def __repr__(self):
        return "{name}({items})".format(
            name=self.__class__.__name__,
            items=", ".join([f"{k}={repr(v)}" for k, v in self.__dict__.items()])
        )

    def __str__(self):
        rep = ""
        last_track_type = None
        tracks = [*list(self), *self.chapters]
        for track in sorted(tracks, key=lambda t: self.TRACK_ORDER_MAP[type(t)]):
            if type(track) != last_track_type:
                last_track_type = type(track)
                count = sum(type(x) is type(track) for x in tracks)
                rep += "{count} {type} Track{plural}{colon}\n".format(
                    count=count,
                    type=track.__class__.__name__.replace("Track", ""),
                    plural="s" if count != 1 else "",
                    colon=":" if count > 0 else ""
                )
            rep += f"{track}\n"

        return rep.rstrip()

    def exists(self, by_id=None, by_url=None):
        """Check if a track already exists by various methods."""
        if by_id:  # recommended
            return any(x.id == by_id for x in self)
        if by_url:
            return any(x.url == by_url for x in self)
        return False

    def add(self, tracks, warn_only=True):
        """Add a provided track to its appropriate array and ensuring it's not a duplicate."""
        if isinstance(tracks, Tracks):
            tracks = [*list(tracks), *tracks.chapters]

        duplicates = 0
        for track in as_list(tracks):
            if self.exists(by_id=track.id):
                if not warn_only:
                    raise ValueError(
                        "One or more of the provided Tracks is a duplicate. "
                        "Track IDs must be unique but accurate using static values. The "
                        "value should stay the same no matter when you request the same "
                        "content. Use a value that has relation to the track content "
                        "itself and is static or permanent and not random/RNG data that "
                        "wont change each refresh or conflict in edge cases."
                    )
                duplicates += 1
                continue

            if isinstance(track, VideoTrack):
                self.videos.append(track)
            elif isinstance(track, AudioTrack):
                self.audios.append(track)
            elif isinstance(track, TextTrack):
                self.subtitles.append(track)
            elif isinstance(track, MenuTrack):
                self.chapters.append(track)
            else:
                raise ValueError("Track type was not set or is invalid.")

        log = logging.getLogger("Tracks")

        if duplicates:
            log.warning(f" - Found and skipped {duplicates} duplicate tracks")

    def print(self, level=logging.INFO):
        """Print the __str__ to log at a specified level."""
        log = logging.getLogger("Tracks")
        for line in str(self).splitlines(keepends=False):
            log.log(level, line)

    def sort_videos(self, by_language=None):
        """Sort video tracks by bitrate, and optionally language."""
        if not self.videos:
            return
        # bitrate
        self.videos = sorted(self.videos, key=lambda x: float(x.bitrate or 0.0), reverse=True)
        # language
        for language in reversed(by_language or []):
            if str(language) == "all":
                language = next((x.language for x in self.videos if x.is_original_lang), "")
            if not language:
                continue
            self.videos = sorted(
                self.videos,
                key=lambda x: "" if is_close_match(language, [x.language]) else str(x.language)
            )

    def sort_audios(self, by_language=None):
        """Sort audio tracks by bitrate, descriptive, and optionally language."""
        if not self.audios:
            return
        # bitrate
        self.audios = sorted(self.audios, key=lambda x: float(x.bitrate or 0.0), reverse=True)
        # channels
        self.audios = sorted(self.audios, key=lambda x: float(x.channels.replace("ch", "").replace("/JOC", "") if x.channels is not None else 0.0), reverse=True)
        # descriptive
        self.audios = sorted(self.audios, key=lambda x: str(x.language) if x.descriptive else "")
        # language
        for language in reversed(by_language or []):
            if str(language) == "all":
                language = next((x.language for x in self.audios if x.is_original_lang), "")
            if not language:
                continue
            self.audios = sorted(
                self.audios,
                key=lambda x: "" if is_close_match(language, [x.language]) else str(x.language)
            )

    def sort_subtitles(self, by_language=None):
        """Sort subtitle tracks by sdh, cc, forced, and optionally language."""
        if not self.subtitles:
            return
        # sdh/cc
        self.subtitles = sorted(
            self.subtitles, key=lambda x: str(x.language) + ("-cc" if x.cc else "") + ("-sdh" if x.sdh else "")
        )
        # forced
        self.subtitles = sorted(self.subtitles, key=lambda x: not x.forced)
        # language
        for language in reversed(by_language or []):
            if str(language) == "all":
                language = next((x.language for x in self.subtitles if x.is_original_lang), "")
            if not language:
                continue
            self.subtitles = sorted(
                self.subtitles,
                key=lambda x: "" if is_close_match(language, [x.language]) else str(x.language)
            )

    def sort_chapters(self):
        """Sort chapter tracks by chapter number."""
        if not self.chapters:
            return
        # number
        self.chapters = sorted(self.chapters, key=lambda x: x.number)

    @staticmethod
    def select_by_language(languages, tracks, one_per_lang=True):
        """
        Filter a track list by language.

        If one_per_lang is True, only the first matched track will be returned for
        each language. It presumes the first match is what is wanted.

        This means if you intend for it to return the best track per language,
        then ensure the iterable is sorted in ascending order (first = best, last = worst).
        """
        if "orig" in languages:
            nonoriglangs = languages.remove("orig")
        else: nonoriglangs = languages
        if not tracks:
            return
        if "all" not in languages:
            track_type = tracks[0].__class__.__name__.lower().replace("track", "").replace("text", "subtitle")
            orig_tracks = tracks
            tracks = [
                x for x in tracks
                if is_close_match(x.language, languages) or (x.is_original_lang and "orig" in languages and not any(lang in x.language for lang in nonoriglangs))
            ]
            if not tracks:
                if languages == ["orig"]:
                    all_languages = set(x.language for x in orig_tracks)
                    if len(all_languages) == 1:
                        # If there's only one language available, take it
                        languages = list(all_languages)
                        tracks = [
                            x for x in orig_tracks
                            if is_close_match(x.language, languages) or (x.is_original_lang and "orig" in languages)
                        ]
                    else:
                        raise ValueError(
                            f"There's no original {track_type} track. Please specify a language manually with "
                            f"{'-al' if track_type == 'audio' else '-sl'}."
                        )
                else:
                    raise ValueError(
                        f"There's no {track_type} tracks that match the language{'' if len(languages) == 1 else 's'}: "
                        f"{', '.join(languages)}"
                    )
        if one_per_lang:
            if "all" in languages:
                languages = list(sorted(set(x.language for x in tracks), key=str))
            for language in languages:
                if language == "orig":
                    yield next(x for x in tracks if x.is_original_lang)
                else:
                    match = get_closest_match(language, [x.language for x in tracks])
                    if match:
                        yield next(x for x in tracks if x.language == match)
        else:
            for track in tracks:
                yield track

    def select_videos (self, by_language=None, by_vbitrate=None, by_quality=None, by_range=None, 
        one_only: bool = True, by_codec=None,
    ) -> None:
        """Filter video tracks by language and other criteria."""
        if by_quality:
            # Note: Do not merge these list comprehensions. They must be done separately so the results
            # from the 16:9 canvas check is only used if there's no exact height resolution match.
            videos_quality = [x for x in self.videos if x.height == by_quality]
            if not videos_quality:
                videos_quality = [x for x in self.videos if int(x.width * (9 / 16)) == by_quality]
            if not videos_quality:
                # AMZN weird resolution (1248x520)
                videos_quality = [x for x in self.videos if x.width == 1248 and by_quality == 720]
            if not videos_quality:
                videos_quality = [x for x in self.videos if (x.width, x.height) < (1024, 576) and by_quality == "SD"]
            if not videos_quality:
                videos_quality = [
                    x for x in self.videos if isinstance(x.extra, dict) and x.extra.get("quality") == by_quality
                ]
            if not videos_quality:
                raise ValueError(f"There's no {by_quality}p resolution video track. Aborting.")
            self.videos = videos_quality
        if by_vbitrate:
            self.videos = [x for x in self.videos if int(x.bitrate) <= int(by_vbitrate * 1001)]
        if by_codec:
            codec_videos = list(filter(lambda x: any(y for y in self.VIDEO_CODEC_MAP[by_codec] if y in x.codec), self.videos))
            if not codec_videos and not should_fallback:
                raise ValueError(f"There's no {by_codec} video tracks. Aborting.")
            else:
                self.videos = (codec_videos if codec_videos else self.videos)
        if by_range:
            self.videos = [x for x in self.videos if {
                "HDR10": x.hdr10,
                "HLG": x.hlg,
                "DV": x.dv,
                "SDR": not x.hdr10 and not x.dv
            }.get((by_range or "").upper(), True)]
            if not self.videos:
                raise ValueError(f"There's no {by_range} video track. Aborting.")
        if by_language:
            self.videos = list(self.select_by_language(by_language, self.videos))
        if one_only and self.videos:
            self.videos = [self.videos[0]]

    def select_audios(
        self,
        with_descriptive: bool = True,
        with_atmos: bool = False,
        by_language=None,
        by_bitrate=None,
        by_channels=None,
        by_codec=None,
        should_fallback: bool = False
    ) -> None:
        """Filter audio tracks by language and other criteria."""
        if not with_descriptive:
            self.audios = [x for x in self.audios if not x.descriptive]
        if by_codec:
            codec_audio = list(filter(lambda x: any(y for y in self.AUDIO_CODEC_MAP[by_codec] if y in x.codec), self.audio))
            if not codec_audio and not should_fallback:
                raise ValueError(f"There's no {by_codec} audio tracks. Aborting.")
            else:
                self.audios = (codec_audio if codec_audio else self.audios)
        if by_channels:
            channels_audio = list(filter(lambda x: x.channels == by_channels, self.audios))
            if not channels_audio and not should_fallback:
                raise ValueError(f"There's no {by_channels} {by_codec} audio tracks. Aborting.")
            else:
                self.audios = (channels_audio if channels_audio else self.audios)
        if with_atmos:
            atmos_audio = list(filter(lambda x: x.atmos, self.audios))
            self.audios = (atmos_audio if atmos_audio else self.audios)  # Fallback if no atmos
        if by_bitrate:
            self.audios = [x for x in self.audios if int(x.bitrate) <= int(by_bitrate * 1000)]
        if by_language:
            # Todo: Optimize select_by_language
            self.audios = list(self.select_by_language(by_language, self.audios, one_per_lang=True)) + \
                          list(self.select_by_language(by_language, [x for x in self.audios if x.descriptive], one_per_lang=True))

    def select_subtitles(self, by_language=None, with_cc=True, with_sdh=True, with_forced=True):
        """Filter subtitle tracks by language and other criteria."""
        if not with_cc:
            self.subtitles = [x for x in self.subtitles if not x.cc]
        if not with_sdh:
            self.subtitles = [x for x in self.subtitles if not x.sdh]
        if isinstance(with_forced, list):
            self.subtitles = [
                x for x in self.subtitles
                if not x.forced or is_close_match(x.language, with_forced)
            ]
        if not with_forced:
            self.subtitles = [x for x in self.subtitles if not x.forced]
        if by_language:
            self.subtitles = list(self.select_by_language(by_language, self.subtitles, one_per_lang=True))

    def export_chapters(self, to_file=None):
        """Export all chapters in order to a string or file."""
        self.sort_chapters()
        data = "\n".join(map(repr, self.chapters))
        if to_file:
            os.makedirs(os.path.dirname(to_file), exist_ok=True)
            with open(to_file, "w", encoding="utf-8") as fd:
                fd.write(data)
        return data

    # converter code

    @staticmethod
    def from_m3u8(*args, **kwargs):
        from vinetrimmer import parsers
        return parsers.m3u8.parse(*args, **kwargs)

    @staticmethod
    def from_mpd(*args, **kwargs):
        from vinetrimmer import parsers
        return parsers.mpd.parse(**kwargs)

    @staticmethod
    def from_ism(*args, **kwargs):
        from vinetrimmer import parsers
        return parsers.ism.parse(**kwargs)

    def mux(self, prefix):
        """
        Takes the Video, Audio and Subtitle Tracks, and muxes them into an MKV file.
        It will attempt to detect Forced/Default tracks, and will try to parse the language codes of the Tracks
        """
        if self.videos:
            muxed_location = self.videos[0].locate()
            if not muxed_location:
                raise ValueError("The provided video track has not yet been downloaded.")
            muxed_location = os.path.splitext(muxed_location)[0] + ".muxed.mkv"
        elif self.audios:
            muxed_location = self.audios[0].locate()
            if not muxed_location:
                raise ValueError("A provided audio track has not yet been downloaded.")
            muxed_location = os.path.splitext(muxed_location)[0] + ".muxed.mka"
        elif self.subtitles:
            muxed_location = self.subtitles[0].locate()
            if not muxed_location:
                raise ValueError("A provided subtitle track has not yet been downloaded.")
            muxed_location = os.path.splitext(muxed_location)[0] + ".muxed.mks"
        elif self.chapters:
            muxed_location = config.filenames.chapters.format(filename=prefix)
            if not muxed_location:
                raise ValueError("A provided chapter has not yet been downloaded.")
            muxed_location = os.path.splitext(muxed_location)[0] + ".muxed.mks"
        else:
            raise ValueError("No tracks provided, at least one track must be provided.")

        muxed_location = os.path.join(config.directories.downloads, os.path.basename(muxed_location))

        cl = [
            "mkvmerge",
            "--output",
            muxed_location
        ]

        for i, vt in enumerate(self.videos):
            location = vt.locate()
            if not location:
                raise ValueError("Somehow a Video Track was not downloaded before muxing...")
            cl.extend([
                "--language", "0:und",
                "--disable-language-ietf",
                "--default-track", f"0:{i == 0}",
                "--compression", "0:none",  # disable extra compression
                "(", location, ")"
            ])
        for i, at in enumerate(self.audios):
            location = at.locate()
            if not location:
                raise ValueError("Somehow an Audio Track was not downloaded before muxing...")
            cl.extend([
                "--track-name", f"0:{at.get_track_name() or ''}",
                "--language", "0:{}".format(LANGUAGE_MUX_MAP.get(
                    str(at.language), at.language.to_alpha3()
                )),
                "--disable-language-ietf",
                "--default-track", f"0:{i == 0}",
                "--compression", "0:none",  # disable extra compression
                "(", location, ")"
            ])
        for st in self.subtitles:
            location = st.locate()
            if not location:
                raise ValueError("Somehow a Text Track was not downloaded before muxing...")
            default = bool(self.audios and is_close_match(st.language, [self.audios[0].language]) and st.forced)
            cl.extend([
                "--track-name", f"0:{st.get_track_name() or ''}",
                "--language", "0:{}".format(LANGUAGE_MUX_MAP.get(
                    str(st.language), st.language.to_alpha3()
                )),
                "--disable-language-ietf",
                "--sub-charset", "0:UTF-8",
                "--forced-track", f"0:{st.forced}",
                "--default-track", f"0:{default}",
                "--compression", "0:none",  # disable extra compression (probably zlib)
                "(", location, ")"
            ])
        if self.chapters:
            location = config.filenames.chapters.format(filename=prefix)
            self.export_chapters(location)
            cl.extend(["--chapters", location])

        # let potential failures go to caller, caller should handle
        p = subprocess.Popen(cl, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        in_progress = False
        for line in TextIOWrapper(p.stdout, encoding="utf-8"):
            if re.search(r"Using the (?:demultiplexer|output module) for the format", line):
                continue
            if line.startswith("Progress:"):
                in_progress = True
                sys.stdout.write("\r" + line.rstrip('\n'))
            else:
                if in_progress:
                    in_progress = False
                    sys.stdout.write("\n")
                sys.stdout.write(line)
        returncode = p.wait()
        return muxed_location, returncode
