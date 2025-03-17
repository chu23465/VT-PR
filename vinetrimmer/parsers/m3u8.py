import base64
import re
from hashlib import md5

from vinetrimmer.objects import AudioTrack, TextTrack, Track, Tracks, VideoTrack
from vinetrimmer.utils import Cdm
from vinetrimmer.vendor.pymp4.parser import Box


def parse(master, source=None):
    """
    Convert a Variant Playlist M3U8 document to a Tracks object with Video, Audio and
    Subtitle Track objects. This is not an M3U8 parser, use https://github.com/globocom/m3u8
    to parse, and then feed the parsed M3U8 object.

    :param master: M3U8 object of the `m3u8` project: https://github.com/globocom/m3u8
    :param source: Source tag for the returned tracks.

    The resulting Track objects' URL will be to another M3U8 file, but this time to an
    actual media stream and not to a variant playlist. The m3u8 downloader code will take
    care of that, as the tracks downloader will be set to `M3U8`.

    Don't forget to manually handle the addition of any needed or extra information or values.
    Like `encrypted`, `pssh`, `hdr10`, `dv`, e.t.c. Essentially anything that is per-service
    should be looked at. Some of these values like `pssh` and `dv` will try to be set automatically
    if possible but if you definitely have the values in the service, then set them.
    Subtitle Codec will default to vtt as it has no codec information.

    Example:
        tracks = Tracks.from_m3u8(m3u8.load(url))
        # check the m3u8 project for more info and ways to parse m3u8 documents
    """
    if not master.is_variant:
        raise ValueError("Tracks.from_m3u8: Expected a Variant Playlist M3U8 document...")

    # get pssh if available
    # uses master.data.session_keys instead of master.keys as master.keys is ONLY EXT-X-KEYS and
    # doesn't include EXT-X-SESSION-KEYS which is whats used for variant playlist M3U8.
    keys = [x.uri for x in master.session_keys if x.keyformat.lower() == "com.microsoft.playready"]
    pssh = keys[0].split(",")[-1] if keys else None
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

    return Tracks(
        # VIDEO
        [VideoTrack(
            id_=md5(str(x).encode()).hexdigest()[0:7],  # 7 chars only for filename length
            source=source,
            url=("" if re.match("^https?://", x.uri) else x.base_uri) + x.uri,
            # metadata
            codec=x.stream_info.codecs.split(",")[0].split(".")[0],  # first codec may not be for the video
            language=None,  # playlists don't state the language, fallback must be used
            bitrate=x.stream_info.average_bandwidth or x.stream_info.bandwidth,
            width=x.stream_info.resolution[0],
            height=x.stream_info.resolution[1],
            fps=x.stream_info.frame_rate,
            hdr10=(x.stream_info.codecs.split(".")[0] not in ("dvhe", "dvh1")
                   and (x.stream_info.video_range or "SDR").strip('"') != "SDR"),
            hlg=False,  # TODO: Can we get this from the manifest?
            dv=x.stream_info.codecs.split(".")[0] in ("dvhe", "dvh1"),
            # switches/options
            descriptor=Track.Descriptor.M3U,
            # decryption
            encrypted=bool(master.keys or master.session_keys),
            pssh=pssh,
            # extra
            extra=x
        ) for x in master.playlists],
        # AUDIO
        [AudioTrack(
            id_=md5(str(x).encode()).hexdigest()[0:6],
            source=source,
            url=("" if re.match("^https?://", x.uri) else x.base_uri) + x.uri,
            # metadata
            codec=x.group_id.replace("audio-", "").split("-")[0].split(".")[0],
            language=x.language,
            bitrate=0,  # TODO: M3U doesn't seem to state bitrate?
            channels=x.channels,
            atmos=(x.channels or "").endswith("/JOC"),
            descriptive="public.accessibility.describes-video" in (x.characteristics or ""),
            # switches/options
            descriptor=Track.Descriptor.M3U,
            # decryption
            encrypted=False,  # don't know for sure if encrypted
            pssh=pssh,
            # extra
            extra=x
        ) for x in master.media if x.type == "AUDIO" and x.uri],
        # SUBTITLES
        [TextTrack(
            id_=md5(str(x).encode()).hexdigest()[0:6],
            source=source,
            url=("" if re.match("^https?://", x.uri) else x.base_uri) + x.uri,
            # metadata
            codec="vtt",  # assuming VTT, codec info isn't shown
            language=x.language,
            forced=x.forced == "YES",
            sdh="public.accessibility.describes-music-and-sound" in (x.characteristics or ""),
            # switches/options
            descriptor=Track.Descriptor.M3U,
            # extra
            extra=x
        ) for x in master.media if x.type == "SUBTITLES"]
    )
