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
    Convert an MPEG-DASH MPD (Media Presentation Description) document to a Tracks object
    with video, audio and subtitle track objects where available.

    :param url: URL of the MPD document.
    :param data: The MPD document as a string.
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
        url = "http://media.developer.dolby.com/DolbyVision_Atmos/profile8.1_DASH/p8.1.mpd"
        session = requests.Session(headers={"X-Example": "foo"})
        tracks = Tracks.from_mpd(
            url,
            session=session,
            source="DOLBY",
        )

        url = "http://media.developer.dolby.com/DolbyVision_Atmos/profile8.1_DASH/p8.1.mpd"
        session = requests.Session(headers={"X-Example": "foo"})
        tracks = Tracks.from_mpd(url=url, data=session.get(url).text, source="DOLBY")
    """
    tracks = []
    if not data:
        if not url:
            raise ValueError("Neither a URL nor a document was provided to Tracks.from_mpd")
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
    if root.tag != "MPD":
        raise ValueError("Non-MPD document provided to Tracks.from_mpd")

    for period in root.findall("Period"):
        if source == "HULU" and next(iter(period.xpath("SegmentType/@value")), "content") != "content":
            continue

        period_base_url = period.findtext("BaseURL") or root.findtext("BaseURL")
        if url and not period_base_url or not re.match("^https?://", period_base_url.lower()):
            period_base_url = urllib.parse.urljoin(url, period_base_url)
            period_base_url = period_base_url.replace('manifests.api.hbo.com', 'cmaf.cf.eu.hbomaxcdn.com')

        for adaptation_set in period.findall("AdaptationSet"):
            if any(x.get("schemeIdUri") == "http://dashif.org/guidelines/trickmode"
                   for x in adaptation_set.findall("EssentialProperty")
                   + adaptation_set.findall("SupplementalProperty")):
                # Skip trick mode streams (used for fast forward/rewind)
                continue

            for rep in adaptation_set.findall("Representation"):
                # content type
                try:
                    content_type = next(x for x in [
                        rep.get("contentType"),
                        rep.get("mimeType"),
                        adaptation_set.get("contentType"),
                        adaptation_set.get("mimeType")
                    ] if bool(x))
                except StopIteration:
                    raise ValueError("No content type value could be found")
                else:
                    content_type = content_type.split("/")[0]
                if content_type.startswith("image"):
                    continue  # most likely seek thumbnails
                # codec
                codecs = rep.get("codecs") or adaptation_set.get("codecs")
                if content_type == "text":
                    mime = adaptation_set.get("mimeType")
                    if mime and not mime.endswith("/mp4"):
                        codecs = mime.split("/")[1]
                # language
                track_lang = None
                for lang in [rep.get("lang"), adaptation_set.get("lang")]:
                    lang = (lang or "").strip()
                    if not lang:
                        continue
                    try:
                        t = Language.get(lang.split("-")[0])
                        if t == Language.get("und") or not t.is_valid():
                            raise LanguageTagError()
                    except LanguageTagError:
                        continue
                    else:
                        track_lang = Language.get(lang)
                        break

                # content protection
                protections = rep.findall("ContentProtection") + adaptation_set.findall("ContentProtection")
                encrypted = bool(protections)
                pssh = None
                kid = None
                for protection in protections:
                    # For HMAX, the PSSH has multiple keys but the PlayReady ContentProtection tag
                    # contains the correct KID
                    kid = protection.get("default_KID")
                    if kid:
                        kid = uuid.UUID(kid).hex
                    else:
                        kid = protection.get("kid")
                        if kid:
                            kid = uuid.UUID(bytes_le=base64.b64decode(kid)).hex
                    if (protection.get("schemeIdUri") or "").lower() != "urn:uuid:9a04f079-9840-4286-ab92-e65be0885f95":
                        continue
                    pssh = protection.findtext("pssh")


                rep_base_url = rep.findtext("BaseURL")
                if rep_base_url and source not in ["DSCP", "DSNY"]:  # TODO: Don't hardcode services
                    # this mpd allows us to download the entire file in one go, no segmentation necessary!
                    if not re.match("^https?://", rep_base_url.lower()):
                        rep_base_url = urllib.parse.urljoin(period_base_url, rep_base_url)
                    query = urllib.parse.urlparse(url).query
                    if query and not urllib.parse.urlparse(rep_base_url).query:
                        rep_base_url += "?" + query
                    track_url = rep_base_url

                else:
                    # this mpd provides no way to download the entire file in one go :(
                    segment_template = rep.find("SegmentTemplate")
                    if segment_template is None:
                        segment_template = adaptation_set.find("SegmentTemplate")
                    if segment_template is None:
                        raise ValueError("Couldn't find a SegmentTemplate for a Representation.")
                    segment_template = copy(segment_template)

                    # join value with base url
                    for item in ("initialization", "media"):
                        if not segment_template.get(item):
                            continue
                        segment_template.set(
                            item, segment_template.get(item).replace("$RepresentationID$", rep.get("id"))
                        )
                        query = urllib.parse.urlparse(url).query
                        if query and not urllib.parse.urlparse(segment_template.get(item)).query:
                            segment_template.set(item, segment_template.get(item) + "?" + query)
                        if not re.match("^https?://", segment_template.get(item).lower()):
                            segment_template.set(item, urllib.parse.urljoin(
                                period_base_url if not rep_base_url else rep_base_url, segment_template.get(item)
                            ))

                    period_duration = period.get("duration")
                    if period_duration:
                        period_duration = Track.pt_to_sec(period_duration)
                    mpd_duration = root.get("mediaPresentationDuration")
                    if mpd_duration:
                        mpd_duration = Track.pt_to_sec(mpd_duration)

                    track_url = []

                    def replace_fields(url, **kwargs):
                        for field, value in kwargs.items():
                            url = url.replace(f"${field}$", str(value))
                            m = re.search(fr"\${re.escape(field)}%([a-z0-9]+)\$", url, flags=re.I)
                            if m:
                                url = url.replace(m.group(), f"{value:{m.group(1)}}")
                        return url

                    initialization = segment_template.get("initialization")
                    if initialization:
                        # header/init segment
                        track_url.append(replace_fields(
                            initialization,
                            Bandwidth=rep.get("bandwidth"),
                            RepresentationID=rep.get("id")
                        ))

                    start_number = int(segment_template.get("startNumber") or 1)

                    segment_timeline = segment_template.find("SegmentTimeline")
                    if segment_timeline is not None:
                        seg_time_list = []
                        current_time = 0
                        for s in segment_timeline.findall("S"):
                            if s.get("t"):
                                current_time = int(s.get("t"))
                            for _ in range(1 + (int(s.get("r") or 0))):
                                seg_time_list.append(current_time)
                                current_time += int(s.get("d"))
                        seg_num_list = list(range(start_number, len(seg_time_list) + start_number))
                        track_url += [
                            replace_fields(
                                segment_template.get("media"),
                                Bandwidth=rep.get("bandwidth"),
                                Number=n,
                                RepresentationID=rep.get("id"),
                                Time=t
                            )
                            for t, n in zip(seg_time_list, seg_num_list)
                        ]
                    else:
                        period_duration = period_duration or mpd_duration
                        segment_duration = (
                            float(segment_template.get("duration")) / float(segment_template.get("timescale") or 1)
                        )
                        total_segments = math.ceil(period_duration / segment_duration)
                        track_url += [
                            replace_fields(
                                segment_template.get("media"),
                                Bandwidth=rep.get("bandwidth"),
                                Number=s,
                                RepresentationID=rep.get("id"),
                                Time=s
                            )
                            for s in range(start_number, start_number + total_segments)
                        ]

                # for some reason it's incredibly common for services to not provide
                # a good and actually unique track ID, sometimes because of the lang
                # dialect not being represented in the id, or the bitrate, or such.
                # this combines all of them as one and hashes it to keep it small(ish).
                track_id = "{codec}-{lang}-{bitrate}-{extra}".format(
                    codec=codecs,
                    lang=track_lang,
                    bitrate=rep.get("bandwidth") or 0,  # subs may not state bandwidth
                    extra=(adaptation_set.get("audioTrackId") or "") + (rep.get("id") or ""),
                )
                track_id = md5(track_id.encode()).hexdigest()

                if content_type == "video":
                    tracks.append(VideoTrack(
                        id_=track_id,
                        source=source,
                        url=track_url,
                        # metadata
                        codec=(codecs or "").split(".")[0],
                        language=track_lang,
                        bitrate=rep.get("bandwidth"),
                        width=int(rep.get("width") or 0) or adaptation_set.get("width"),
                        height=int(rep.get("height") or 0) or adaptation_set.get("height"),
                        fps=rep.get("frameRate") or adaptation_set.get("frameRate"),
                        hdr10=any(
                            x.get("schemeIdUri") == "urn:mpeg:mpegB:cicp:TransferCharacteristics"
                            and x.get("value") == "16"  # PQ
                            for x in adaptation_set.findall("SupplementalProperty")
                        ) or any(
                            x.get("schemeIdUri") == "http://dashif.org/metadata/hdr"
                            and x.get("value") == "SMPTE2094-40"  # HDR10+
                            for x in adaptation_set.findall("SupplementalProperty")
                        ),
                        hlg=any(
                            x.get("schemeIdUri") == "urn:mpeg:mpegB:cicp:TransferCharacteristics"
                            and x.get("value") == "18"  # HLG
                            for x in adaptation_set.findall("SupplementalProperty")
                        ),
                        dv=codecs and codecs.startswith(("dvhe", "dvh1")),
                        # switches/options
                        descriptor=Track.Descriptor.MPD,
                        # decryption
                        encrypted=encrypted,
                        pssh=pssh,
                        kid=kid,
                        # extra
                        extra=(rep, adaptation_set)
                    ))
                elif content_type == "audio":
                    tracks.append(AudioTrack(
                        id_=track_id,
                        source=source,
                        url=track_url,
                        # metadata
                        codec=(codecs or "").split(".")[0],
                        language=track_lang,
                        bitrate=rep.get("bandwidth"),
                        channels=next(iter(
                            rep.xpath("AudioChannelConfiguration/@value")
                            or adaptation_set.xpath("AudioChannelConfiguration/@value")
                        ), None),
                        descriptive=any(
                            x.get("schemeIdUri") == "urn:mpeg:dash:role:2011" and x.get("value") == "description"
                            for x in adaptation_set.findall("Accessibility")
                        ),
                        # switches/options
                        descriptor=Track.Descriptor.MPD,
                        # decryption
                        encrypted=encrypted,
                        pssh=pssh,
                        kid=kid,
                        # extra
                        extra=(rep, adaptation_set)
                    ))
                elif content_type == "text":
                    if source == 'HMAX':
                        # HMAX SUBS
                        segment_template = rep.find("SegmentTemplate")

                        sub_path_url = rep.findtext("BaseURL")
                        if not sub_path_url:
                            sub_path_url = segment_template.get('media')
                       
                        try:
                            path = re.search(r'(t\/.+?\/)t', sub_path_url).group(1)
                        except AttributeError:
                            path = 't/sub/'
                        
                        is_normal = any(x.get("value") == "subtitle" for x in adaptation_set.findall("Role"))
                        is_sdh = any(x.get("value") == "caption" for x in adaptation_set.findall("Role"))
                        is_forced = any(x.get("value") == "forced-subtitle" for x in adaptation_set.findall("Role"))

                        if is_normal:
                            track_url = [base_url + path + adaptation_set.get('lang') + '_sub.vtt']
                        elif is_sdh:
                            track_url = [base_url + path + adaptation_set.get('lang') + '_sdh.vtt']
                        elif is_forced:
                            track_url = [base_url + path + adaptation_set.get('lang') + '_forced.vtt']

                        tracks.append(TextTrack(
                            id_=track_id,
                            source=source,
                            url=track_url,
                            # metadata
                            codec=(codecs or "").split(".")[0],
                            language=track_lang,
                            forced=is_forced,
                            sdh=is_sdh,
                            # switches/options
                            descriptor=Track.Descriptor.MPD,
                            # extra
                            extra=(rep, adaptation_set)
                        ))
                    else:
                        tracks.append(TextTrack(
                            id_=track_id,
                            source=source,
                            url=track_url,
                            # metadata
                            codec=(codecs or "").split(".")[0],
                            language=track_lang,
                            # switches/options
                            descriptor=Track.Descriptor.MPD,
                            # extra
                            extra=(rep, adaptation_set)
                        ))

    # r = session.get(url=url)
    # mpd = json.loads(json.dumps(xmltodict.parse(r.text)))
    # period = mpd['MPD']['Period']

    # try:
    #     base_url = urllib.parse.urljoin(mpd['MPD']['BaseURL'], period['BaseURL'])
    #     print('1', base_url)
    # except KeyError:
    #     base_url = url.rsplit('/', 1)[0] + '/'

    # try:
    #     stracks = []
    #     for pb in period:
    #         stracks = stracks + pb['AdaptationSet']
    # except TypeError:
    #     stracks = period['AdaptationSet']

    # def force_instance(item):
    #     if isinstance(item['Representation'], list):
    #         X = item['Representation']
    #     else:
    #         X = [item['Representation']]
    #     return X

    # # subtitles
    # subs_list = []
    # for subs_tracks in stracks:
    #     if subs_tracks['@contentType'] == 'text':
    #         for x in force_instance(subs_tracks):

    #             try:
    #                 sub_path_url = x['BaseURL']
    #             except KeyError:
    #                 sub_path_url = x['SegmentTemplate']['@media']

    #             try:
    #                 path = re.search(r'(t\/.+?\/)t', sub_path_url).group(1)
    #             except AttributeError:
    #                 path = 't/sub/'

    #             isCC = False
    #             if subs_tracks["Role"]["@value"] == "caption":
    #                 isCC = True
    #             isNormal = False
                
    #             if isCC:
    #                 lang_id = str(Language.get(subs_tracks['@lang'])) + '-sdh'
    #                 sub_url = base_url + path + subs_tracks['@lang'] + '_sdh.vtt'
    #                 trackType = 'SDH'
    #             else:
    #                 lang_id = str(Language.get(subs_tracks['@lang']))
    #                 sub_url = base_url + path + subs_tracks['@lang'] + '_sub.vtt'
    #                 isNormal = True
    #                 trackType = 'NORMAL'

    #             isForced = False
    #             if subs_tracks["Role"]["@value"] == "forced-subtitle":
    #                 isForced = True
    #                 isNormal = False
    #                 trackType = 'FORCED'
    #                 lang_id = str(Language.get(subs_tracks['@lang'])) + '-forced'
    #                 sub_url = base_url + path + subs_tracks['@lang'] + '_forced.vtt'
     

    #             tracks.append(TextTrack(
    #                 id_=lang_id,
    #                 source=source,
    #                 url=sub_url,
    #                 # metadata
    #                 codec=(codecs or "").split(".")[0],
    #                 language=str(Language.get(subs_tracks['@lang'])),
    #                 forced=isForced,
    #                 sdh=isCC,
    #                 # switches/options
    #                 descriptor=Track.Descriptor.MPD,
    #                 # extra
    #                 extra=(x, subs_tracks)
    #             ))


    # Add tracks, but warn only. Assume any duplicate track cannot be handled.
    # Since the custom track id above uses all kinds of data, there realistically would
    # be no other workaround.
    tracks_obj = Tracks()
    tracks_obj.add(tracks, warn_only=True)

    return tracks_obj
