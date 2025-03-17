from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode, quote
from typing import Union

import click
import jsonpickle
import requests
from click import Context
from langcodes import Language
from tldextract import tldextract
from click.core import ParameterSource

from vinetrimmer.objects import TextTrack, Title, Tracks
from vinetrimmer.objects.tracks import MenuTrack
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils import is_close_match
from vinetrimmer.utils.Logger import Logger
from vinetrimmer.utils.widevine.device import LocalDevice


class Amazon(BaseService):
    """
    Service code for Amazon VOD (https://amazon.com) and Amazon Prime Video (https://primevideo.com).

    \b
    Authorization: Cookies
    Security: UHD@L1 FHD@L3(ChromeCDM) SD@L3, Maintains their own license server like Netflix, be cautious.

    \b
    Region is chosen automatically based on domain extension found in cookies.
    Prime Video specific code will be run if the ASIN is detected to be a prime video variant.
    Use 'Amazon Video ASIN Display' for Tampermonkey addon for ASIN
    https://greasyfork.org/en/scripts/381997-amazon-video-asin-display
    
    vt dl --list -z uk -q 1080 Amazon B09SLGYLK8 
    """

    ALIASES = ["AMZN", "amazon"]
    TITLE_RE = r"^(?:https?://(?:www\.)?(?P<domain>amazon\.(?P<region>com|co\.uk|de|co\.jp)|primevideo\.com)(?:/.+)?/)?(?P<id>[A-Z0-9]{10,}|amzn1\.dv\.gti\.[a-f0-9-]+)"  # noqa: E501

    REGION_TLD_MAP = {
        "au": "com.au",
        "br": "com.br",
        "jp": "co.jp",
        "mx": "com.mx",
        "tr": "com.tr",
        "gb": "co.uk",
        "us": "com",
    }
    VIDEO_RANGE_MAP = {
        "SDR": "None",
        "HDR10": "Hdr10",
        "DV": "DolbyVision",
    }

    @staticmethod
    @click.command(name="Amazon", short_help="https://amazon.com, https://primevideo.com", help=__doc__)
    @click.argument("title", type=str, required=False)
    @click.option("-b", "--bitrate", default="CBR",
                  type=click.Choice(["CVBR", "CBR", "CVBR+CBR"], case_sensitive=False),
                  help="Video Bitrate Mode to download in. CVBR=Constrained Variable Bitrate, CBR=Constant Bitrate.")
    @click.option("-c", "--cdn", default=None, type=str,
                  help="CDN to download from, defaults to the CDN with the highest weight set by Amazon.")
    # UHD, HD, SD. UHD only returns HEVC, ever, even for <=HD only content
    @click.option("-vq", "--vquality", default="HD",
                  type=click.Choice(["SD", "HD", "UHD"], case_sensitive=False),
                  help="Manifest quality to request.")
    @click.option("-s", "--single", is_flag=True, default=False,
                  help="Force single episode/season instead of getting series ASIN.")
    @click.option("-am", "--amanifest", default="H265",
                  type=click.Choice(["CVBR", "CBR", "H265"], case_sensitive=False),
                  help="Manifest to use for audio. Defaults to H265 if the video manifest is missing 640k audio.")
    @click.option("-aq", "--aquality", default="SD",
                  type=click.Choice(["SD", "HD", "UHD"], case_sensitive=False),
                  help="Manifest quality to request for audio. Defaults to the same as --quality.")
    @click.pass_context
    def cli(ctx, **kwargs):
        return Amazon(ctx, **kwargs)

    def __init__(self, ctx, title, bitrate: str, cdn: str, vquality: str, single: bool, amanifest: str, aquality: str):
        m = self.parse_title(ctx, title)
        self.bitrate = bitrate
        self.bitrate_source = ctx.get_parameter_source("bitrate")
        self.cdn = cdn
        self.vquality = vquality
        self.vquality_source = ctx.get_parameter_source("vquality")
        self.single = single
        self.amanifest = amanifest
        self.aquality = aquality
        super().__init__(ctx)

        assert ctx.parent is not None

        self.vcodec = ctx.parent.params["vcodec"] or "H264"
        self.range = ctx.parent.params["range_"] or "SDR"
        self.chapters_only = ctx.parent.params["chapters_only"]
        self.atmos = ctx.parent.params["atmos"]
        self.quality = ctx.parent.params.get("quality") or 1080

        self.cdm = ctx.obj.cdm
        self.profile = ctx.obj.profile

        self.region: dict[str, str] = {}
        self.endpoints: dict[str, str] = {}
        self.device: dict[str, str] = {}

        self.pv = False
        self.device_token = None
        self.device_id: None
        self.customer_id = None
        self.client_id = "f22dbddb-ef2c-48c5-8876-bed0d47594fd"  # browser client id



        if self.vquality_source != ParameterSource.COMMANDLINE:
            if 0 < self.quality <= 576 and self.range == "SDR":
                self.log.info(" + Setting manifest quality to SD")
                self.vquality = "SD"

            if self.quality > 1080:
                self.log.info(" + Setting manifest quality to UHD to be able to get 2160p video track")
                self.vquality = "UHD"

        self.vquality = self.vquality or "HD"

        if self.bitrate_source != ParameterSource.COMMANDLINE:
            if self.vcodec == "H265" and self.range == "SDR" and self.bitrate != "CVBR+CBR":
                self.bitrate = "CVBR+CBR"
                self.log.info(" + Changed bitrate mode to CVBR+CBR to be able to get H.265 SDR video track")

            if self.vquality == "UHD" and self.range != "SDR" and self.bitrate != "CBR":
                self.bitrate = "CBR"
                self.log.info(f" + Changed bitrate mode to CBR to be able to get highest quality UHD {self.range} video track")

        self.orig_bitrate = self.bitrate

        self.configure()

    # Abstracted functions

    def get_titles(self):
        res = self.session.get(
            url=self.endpoints["details"],
            params={
                "titleID": self.title,
                "isElcano": "1",
                "sections": ["Atf", "Btf"]
            },
            headers={
                "Accept": "application/json"
            }
        )

        if not res.ok:
            raise self.log.exit(f"Unable to get title: {res.text} [{res.status_code}]")

        data = res.json()["widgets"]
        product_details = data.get("productDetails", {}).get("detail")

        if not product_details:
            error = res.json()["degradations"][0]
            raise self.log.exit(f"Unable to get title: {error['message']} [{error['code']}]")

        titles = []

        if data["pageContext"]["subPageType"] == "Movie":
            card = data["productDetails"]["detail"]
            titles.append(Title(
                id_=card["catalogId"],
                type_=Title.Types.MOVIE,
                name=product_details["title"],
                #year=card["releaseYear"],
                year=card.get("releaseYear", ""),
                # language is obtained afterward
                original_lang=None,
                source=self.ALIASES[0],
                service_data=card
            ))
        else:
            if data["titleContent"] == []:
                episodes = data["episodeList"]["episodes"]
                for episode in episodes:
                    details = episode["detail"]
                    titles.append(
                        Title(
                            id_=details["catalogId"],
                            type_=Title.Types.TV,
                            name=product_details["parentTitle"],
                            season=data["productDetails"]["detail"]["seasonNumber"],
                            episode=episode["self"]["sequenceNumber"],
                            episode_name=details["title"],
                            # language is obtained afterward
                            original_lang=None,
                            source=self.ALIASES[0],
                            service_data=details,
                        )
                    )
                if len(titles) == 25:
                    page_count = 1
                    pagination_data = data.get('episodeList', {}).get('actions', {}).get('pagination', [])
                    token = next((quote(item.get('token')) for item in pagination_data if item.get('tokenType') == 'NextPage'), None)
                    while True:
                        page_count += 1
                        res = self.session.get(
                            url=self.endpoints["getDetailWidgets"],
                            params={
                                "titleID": self.title,
                                "isTvodOnRow": "1",
                                "widgets": f'[{{"widgetType":"EpisodeList","widgetToken":"{token}"}}]'
                            },
                            headers={
                                "Accept": "application/json"
                            }
                        ).json()
                        episodeList = res['widgets'].get('episodeList', {})
                        for item in episodeList.get('episodes', []):
                            episode = int(item.get('self', {}).get('sequenceNumber', {}))
                            titles.append(Title(
                                id_=item["detail"]["catalogId"],
                                type_=Title.Types.TV,
                                name=product_details["parentTitle"],
                                season=product_details["seasonNumber"],
                                episode=episode,
                                episode_name=item["detail"]["title"],
                                # language is obtained afterward
                                original_lang=None,
                                source=self.ALIASES[0],
                                service_data=item
                            ))
                        pagination_data = res['widgets'].get('episodeList', {}).get('actions', {}).get('pagination', [])
                        token = next((quote(item.get('token')) for item in pagination_data if item.get('tokenType') == 'NextPage'), None)
                        if not token:
                            break
            else:
                cards = [
                    x["detail"]
                    for x in data["titleContent"][0]["cards"]
                        if not self.single or
                           (self.single and self.title in data["self"]["asins"]) or (self.single and self.title in data["self"]["compactGTI"]) or
                           (self.single and self.title in x["self"]["asins"]) or (self.single and self.title == x["detail"]["catalogId"])
                ]
                for card in cards:
                    episode_number = card.get("episodeNumber", 0)
                    if episode_number != 0:
                        titles.append(Title(
                            id_=card["catalogId"],
                            type_=Title.Types.TV,
                            name=product_details["parentTitle"],
                            season=product_details["seasonNumber"],
                            episode=episode_number,
                            episode_name=card["title"],
                            # language is obtained afterward
                            original_lang=None,
                            source=self.ALIASES[0],
                            service_data=card
                        ))
            
            if not self.single:
                temp_title = self.title
                temp_single = self.single
            
                self.single = True
                for season in data.get('seasonSelector', []):
                    season_link = season["seasonLink"]
                    match = re.search(r'/([a-zA-Z0-9]+)\/ref=', season_link)    #extract other season id using re 
                    if match:
                        extracted_value = match.group(1)
                        if data["self"]["compactGTI"] == extracted_value:   #skip entered asin season data and grab rest id's
                            continue
                        
                        self.title = extracted_value
                        for title in self.get_titles():
                            titles.append(title)
            
                self.title = temp_title
                self.single = temp_single


        if titles:
            # TODO: Needs playback permission on first title, title needs to be available
            original_lang = self.get_original_language(self.get_manifest(
                next((x for x in titles if x.type == Title.Types.MOVIE or x.episode > 0), titles[0]),
                video_codec=self.vcodec,
                bitrate_mode=self.bitrate,
                quality=self.vquality,
                ignore_errors=True
            ))
            if original_lang:
                for title in titles:
                    title.original_lang = Language.get(original_lang)
            else:
                #self.log.warning(" - Unable to obtain the title's original language, setting 'en' default...")
                for title in titles:
                    title.original_lang = Language.get("en")

        filtered_titles = []
        season_episode_count = defaultdict(int)
        for title in titles:
            key = (title.season, title.episode) 
            if season_episode_count[key] < 1:
                filtered_titles.append(title)
                season_episode_count[key] += 1

        titles = filtered_titles

        return titles

    def get_tracks(self, title: Title) -> Tracks:
        tracks = Tracks()
        if self.chapters_only:
            return []

        manifest, chosen_manifest, tracks = self.get_best_quality(title)

        manifest = self.get_manifest(
            title,
            video_codec=self.vcodec,
            bitrate_mode=self.bitrate,
            quality=self.vquality,
            hdr=self.range,
            ignore_errors=False
            
        )
        
        # Move rightsException termination here so that script can attempt continuing
        if "rightsException" in manifest["returnedTitleRendition"]["selectedEntitlement"]:
            self.log.error(" - The profile used does not have the rights to this title.")
            return

        self.customer_id = manifest["returnedTitleRendition"]["selectedEntitlement"]["grantedByCustomerId"]

        default_url_set = manifest["playbackUrls"]["urlSets"][manifest["playbackUrls"]["defaultUrlSetId"]]
        encoding_version = default_url_set["urls"]["manifest"]["encodingVersion"]
        self.log.info(f" + Detected encodingVersion={encoding_version}")

        chosen_manifest = self.choose_manifest(manifest, self.cdn)

        if not chosen_manifest:
            raise self.log.exit(f"No manifests available")

        manifest_url = self.clean_mpd_url(chosen_manifest["avUrlInfoList"][0]["url"])
        self.log.debug(manifest_url)
        self.log.info(" + Downloading Manifest")

        if chosen_manifest["streamingTechnology"] == "DASH":
            tracks = Tracks([
                x for x in iter(Tracks.from_mpd(
                    url=manifest_url,
                    session=self.session,
                    source=self.ALIASES[0],
                ))
            ])
        elif chosen_manifest["streamingTechnology"] == "SmoothStreaming":
            tracks = Tracks([
                x for x in iter(Tracks.from_ism(
                    url=manifest_url,
                    session=self.session,
                    source=self.ALIASES[0],
                ))
            ])
        else:
            raise self.log.exit(f"Unsupported manifest type: {chosen_manifest['streamingTechnology']}")

        need_separate_audio = ((self.aquality or self.vquality) != self.vquality
                               or self.amanifest == "CVBR" and (self.vcodec, self.bitrate) != ("H264", "CVBR")
                               or self.amanifest == "CBR" and (self.vcodec, self.bitrate) != ("H264", "CBR")
                               or self.amanifest == "H265" and self.vcodec != "H265"
                               or self.amanifest != "H265" and self.vcodec == "H265")

        if not need_separate_audio:
            audios = defaultdict(list)
            
            for audio in tracks.audios:
                audio.descriptive = audio.extra[1].get("audioTrackSubtype") == "descriptive"
                # Amazon @lang is just the lang code, no dialect, @audioTrackId has it.
                audio_track_id = audio.extra[1].get("audioTrackId")
                if audio_track_id:
                    audio.language = Language.get(audio_track_id.split("_")[0])  # e.g. es-419_ec3_blabla
                # Remove any audio tracks with dialog boost!
                if audio.extra[1] is not None and "boosteddialog" in audio.extra[1].get("audioTrackSubtype", ""):
                    tracks.audios.remove(audio)

            for audio in tracks.audios:
                audios[audio.language].append(audio)

            for lang in audios:
                if not any((x.bitrate or 0) >= 640000 for x in audios[lang]):
                    need_separate_audio = True
                    break

        if need_separate_audio and not self.atmos:
            manifest_type = self.amanifest or "H265"
            self.log.info(f"Getting audio from {manifest_type} manifest for potential higher bitrate or better codec")
            audio_manifest = self.get_manifest(
                title=title,
                video_codec="H265" if manifest_type == "H265" else "H264",
                bitrate_mode="CVBR" if manifest_type != "CBR" else "CBR",
                quality=self.aquality or self.vquality,
                hdr=None,
                ignore_errors=True
            )
            if not audio_manifest:
                self.log.warning(f" - Unable to get {manifest_type} audio manifests, skipping")
            elif not (chosen_audio_manifest := self.choose_manifest(audio_manifest, self.cdn)):
                self.log.warning(f" - No {manifest_type} audio manifests available, skipping")
            else:
                audio_mpd_url = self.clean_mpd_url(chosen_audio_manifest["avUrlInfoList"][0]["url"])
                self.log.debug(audio_mpd_url)
                self.log.info(" + Downloading HEVC manifest")

                try:
                    audio_mpd = Tracks([
                        x for x in iter(Tracks.from_mpd(
                            url=audio_mpd_url,
                            session=self.session,
                            source=self.ALIASES[0],
                        ))
                    ])
                except KeyError:
                    self.log.warning(f" - Title has no {self.amanifest} stream, cannot get higher quality audio")
                else:
                    tracks.add(audio_mpd.audios, warn_only=True)  # expecting possible dupes, ignore

        need_uhd_audio = self.atmos

        if not self.amanifest and ((self.aquality == "UHD" and self.vquality != "UHD") or not self.aquality):
            audios = defaultdict(list)
            for audio in tracks.audios:
                audios[audio.language].append(audio)
            for lang in audios:
                if not any((x.bitrate or 0) >= 640000 for x in audios[lang]):
                    need_uhd_audio = True
                    break

        if need_uhd_audio and (self.config.get("device") or {}).get(self.profile, None):
            self.log.info("Getting audio from UHD manifest for potential higher bitrate or better codec")
            temp_device = self.device
            temp_device_token = self.device_token
            temp_device_id = self.device_id
            uhd_audio_manifest = None

            try:
                if self.quality < 2160 or (self.cdm.device.type == LocalDevice.Types.CHROME):
                    self.log.info(f" + Switching to device to get UHD manifest")
                    self.register_device()

                uhd_audio_manifest = self.get_manifest(
                    title=title,
                    video_codec="H265",
                    bitrate_mode="CVBR+CBR",
                    quality="UHD",
                    hdr="DV",  # Needed for 576kbps Atmos sometimes
                    ignore_errors=False
                )
            except:
                self.log.exit()
                

            self.device = temp_device
            self.device_token = temp_device_token
            self.device_id = temp_device_id

            if not uhd_audio_manifest:
                self.log.warning(f" - Unable to get UHD manifests, skipping")
            elif not (chosen_uhd_audio_manifest := self.choose_manifest(uhd_audio_manifest, self.cdn)):
                self.log.warning(f" - No UHD manifests available, skipping")
            else:
                uhd_audio_mpd_url = self.clean_mpd_url(chosen_uhd_audio_manifest["avUrlInfoList"][0]["url"])
                self.log.debug(uhd_audio_mpd_url)
                self.log.info(" + Downloading UHD manifest")

                try:
                    uhd_audio_mpd = Tracks([
                        x for x in iter(Tracks.from_mpd(
                            url=uhd_audio_mpd_url,
                            session=self.session,
                            source=self.ALIASES[0],
                        ))
                    ])
                except KeyError:
                    self.log.warning(f" - Title has no UHD stream, cannot get higher quality audio")
                else:
                    # replace the audio tracks with DV manifest version if atmos is present
                    if any(x for x in uhd_audio_mpd.audios if x.atmos):
                        tracks.audios = uhd_audio_mpd.audios

        for video in tracks.videos:
            video.hdr10 = chosen_manifest["hdrFormat"] == "Hdr10"
            video.dv = chosen_manifest["hdrFormat"] == "DolbyVision"

        for audio in tracks.audios:
            audio.descriptive = audio.extra[1].get("audioTrackSubtype") == "descriptive"
            # Amazon @lang is just the lang code, no dialect, @audioTrackId has it.
            audio_track_id = audio.extra[1].get("audioTrackId")
            if audio_track_id:
                audio.language = Language.get(audio_track_id.split("_")[0])  # e.g. es-419_ec3_blabla

            if audio.extra[1] is not None and "boosteddialog" in audio.extra[1].get("audioTrackSubtype", ""):
                tracks.audios.remove(audio)
    

        for sub in manifest.get("subtitleUrls", []) + manifest.get("forcedNarratives", []):
            tracks.add(TextTrack(
                id_=sub.get(
                    "timedTextTrackId",
                    f"{sub['languageCode']}_{sub['type']}_{sub['subtype']}_{sub['index']}"
                ),
                source=self.ALIASES[0],
                url=os.path.splitext(sub["url"])[0] + ".srt",  # DFXP -> SRT forcefully seems to work fine
                # metadata
                codec="srt",  # sub["format"].lower(),
                language=sub["languageCode"],
                #is_original_lang=title.original_lang and is_close_match(sub["languageCode"], [title.original_lang]),
                forced="forced" in sub["displayName"],
                sdh=sub["type"].lower() == "sdh"  # TODO: what other sub types? cc? forced?
            ), warn_only=True)  # expecting possible dupes, ignore

        return tracks


    def get_chapters(self, title: Title) -> list[MenuTrack]:
        """Get chapters from Amazon's XRay Scenes API."""
        manifest = self.get_manifest(
            title,
            video_codec=self.vcodec,
            bitrate_mode=self.bitrate,
            quality=self.vquality,
            hdr=self.range
        )

        if "xrayMetadata" in manifest:
            xray_params = manifest["xrayMetadata"]["parameters"]
        elif self.chapters_only:
            xray_params = {
                "pageId": "fullScreen",
                "pageType": "xray",
                "serviceToken": json.dumps({
                    "consumptionType": "Streaming",
                    "deviceClass": "normal",
                    "playbackMode": "playback",
                    "vcid": manifest["returnedTitleRendition"]["contentId"],
                })
            }
        else:
            return []

        xray_params.update({
            "deviceID": self.device_id,
            "deviceTypeID": self.config["device_types"]["browser"],  # must be browser device type
            "marketplaceID": self.region["marketplace_id"],
            "gascEnabled": str(self.pv).lower(),
            "decorationScheme": "none",
            "version": "inception-v2",
            "uxLocale": "en-US",
            "featureScheme": "XRAY_WEB_2020_V1"
        })

        xray = self.session.get(
            url=self.endpoints["xray"],
            params=xray_params
        ).json().get("page")

        if not xray:
            return []

        widgets = xray["sections"]["center"]["widgets"]["widgetList"]

        scenes = next((x for x in widgets if x["tabType"] == "scenesTab"), None)
        if not scenes:
            return []
        scenes = scenes["widgets"]["widgetList"][0]["items"]["itemList"]

        chapters = []

        for scene in scenes:
            chapter_title = scene["textMap"]["PRIMARY"]
            match = re.search(r"(\d+\. |)(.+)", chapter_title)
            if match:
                chapter_title = match.group(2)
            chapters.append(MenuTrack(
                number=int(scene["id"].replace("/xray/scene/", "")),
                title=chapter_title,
                timecode=scene["textMap"]["TERTIARY"].replace("Starts at ", "")
            ))

        return chapters

    def certificate(self, **_):
        return self.config["certificate"]

    def license(self, challenge: Union[bytes, str], title: Title, **_):
        lic = self.session.post(
            url=self.endpoints["licence"],
            params={
                "asin": title.id,
                "consumptionType": "Streaming",
                "desiredResources": "PlayReadyLicense",
                "deviceTypeID": self.device["device_type"],
                "deviceID": self.device_id,
                "firmware": 1,
                "gascEnabled": str(self.pv).lower(),
                "marketplaceID": self.region["marketplace_id"],
                "resourceUsage": "ImmediateConsumption",
                "videoMaterialType": "Feature",
                "operatingSystemName": "Linux" if self.vquality == "SD" else "Windows",
                "operatingSystemVersion": "unknown" if self.vquality == "SD" else "10.0",
                "customerID": self.customer_id,
                "deviceDrmOverride": "CENC",
                "deviceStreamingTechnologyOverride": "DASH", # "SmoothStreaming"
                "deviceVideoQualityOverride": self.vquality,
                "deviceHdrFormatsOverride": self.VIDEO_RANGE_MAP.get(self.range, "None"),
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Bearer {self.device_token}"
            },
            data={
                "playReadyChallenge": base64.b64encode(challenge).decode("utf-8") if isinstance(challenge, bytes) else base64.b64encode(challenge.encode("ascii")).decode("utf-8"),  # expects base64
                "includeHdcpTestKeyInLicense": "true"
            }
        ).json()
        if "errorsByResource" in lic:
            print(lic["errorsByResource"])
            error_code = lic["errorsByResource"]["playReadyLicense"]
            if "errorCode" in error_code:
                error_code = error_code["errorCode"]
            elif "type" in error_code:
                error_code = error_code["type"]
            if error_code == "PRS.NoRights.AnonymizerIP":
                raise self.log.exit(" - Amazon detected a Proxy/VPN and refused to return a license!")
            message = lic["errorsByResource"]["playReadyLicense"]["message"]
            raise self.log.exit(f" - Amazon reported an error during the License request: {message} [{error_code}]")
        if "error" in lic:
            error_code = lic["error"]
            if "errorCode" in error_code:
                error_code = error_code["errorCode"]
            elif "type" in error_code:
                error_code = error_code["type"]
            if error_code == "PRS.NoRights.AnonymizerIP":
                raise self.log.exit(" - Amazon detected a Proxy/VPN and refused to return a license!")
            message = lic["error"]["message"]
            raise self.log.exit(f" - Amazon reported an error during the License request: {message} [{error_code}]")
        #self.log.info(lic["playReadyLicense"]["encodedLicenseResponse"])
        return lic["playReadyLicense"]["encodedLicenseResponse"]

    # Service specific functions

    def configure(self) -> None:
        if len(self.title) > 10:
            self.pv = True

        self.log.info("Getting Account Region")
        self.region = self.get_region()
        if not self.region:
            raise self.log.exit(" - Failed to get Amazon Account region")
        self.GEOFENCE.append(self.region["code"])
        self.log.info(f" + Region: {self.region['code']}")

        # endpoints must be prepared AFTER region data is retrieved
        self.endpoints = self.prepare_endpoints(self.config["endpoints"], self.region)

        self.session.headers.update({
            "Origin": f"https://{self.region['base']}"
        })

        self.device = (self.config.get("device") or {}).get(self.profile, {})
        if (self.quality > 1080 or self.range != "SDR") and self.vcodec == "H265" and (self.cdm.device.type == LocalDevice.Types.CHROME if "common_privacy_cert" in dir(self.cdm) else False):
            self.log.info(f"Using device to get UHD manifests")
            self.register_device()
        elif not self.device or self.vquality != "UHD" or (self.cdm.device.type == LocalDevice.Types.CHROME if "common_privacy_cert" in dir(self.cdm) else False):
            # falling back to browser-based device ID
            if not self.device:
                self.log.warning(
                    "No Device information was provided for %s, using browser device...",
                    self.profile
                )
            self.device_id = hashlib.sha224(
                ("CustomerID" + self.session.headers["User-Agent"]).encode("utf-8")
            ).hexdigest()
            self.device = {"device_type": self.config["device_types"]["browser"]}
        else:
            self.register_device()

    def register_device(self) -> None:
        self.device = (self.config.get("device") or {}).get(self.profile, {})
        device_cache_path = self.get_cache("device_tokens_{profile}_{hash}.json".format(
            profile=self.profile,
            hash=hashlib.md5(json.dumps(self.device).encode()).hexdigest()[0:6]
        ))
        self.device_token = self.DeviceRegistration(
            device=self.device,
            endpoints=self.endpoints,
            log=self.log,
            cache_path=device_cache_path,
            session=self.session
        ).bearer
        self.device_id = self.device.get("device_serial")
        if not self.device_id:
            raise self.log.exit(f" - A device serial is required in the config, perhaps use: {os.urandom(8).hex()}")

    def get_region(self) -> dict:
        domain_region = self.get_domain_region()
        if not domain_region:
            return {}

        region = self.config["regions"].get(domain_region)
        if not region:
            raise self.log.exit(f" - There's no region configuration data for the region: {domain_region}")

        region["code"] = domain_region

        if self.pv:
            res = self.session.get("https://www.primevideo.com").text
            match = re.search(r'ue_furl *= *([\'"])fls-(na|eu|fe)\.amazon\.[a-z.]+\1', res)
            if match:
                pv_region = match.group(2).lower()
            else:
                raise self.log.exit(" - Failed to get PrimeVideo region")
            pv_region = {"na": "atv-ps"}.get(pv_region, f"atv-ps-{pv_region}")
            region["base_manifest"] = f"{pv_region}.primevideo.com"
            region["base"] = "www.primevideo.com"

        return region

    def get_domain_region(self):
        """Get the region of the cookies from the domain."""
        tlds = [tldextract.extract(x.domain) for x in self.cookies if x.domain_specified]
        tld = next((x.suffix for x in tlds if x.domain.lower() in ("amazon", "primevideo")), None)
        if tld:
            tld = tld.split(".")[-1]
        return {"com": "us", "uk": "gb"}.get(tld, tld)

    def prepare_endpoint(self, name: str, uri: str, region: dict) -> str:
        if name in ("browse", "playback", "licence", "xray"):
            return f"https://{(region['base_manifest'])}{uri}"
        if name in ("ontv", "devicelink", "details", "getDetailWidgets"):
            if self.pv:
                host = "www.primevideo.com"
            else:
                host = region["base"]
            return f"https://{host}{uri}"
        if name in ("codepair", "register", "token"):
            return f"https://{self.config['regions']['us']['base_api']}{uri}"
        raise ValueError(f"Unknown endpoint: {name}")

    def prepare_endpoints(self, endpoints: dict, region: dict) -> dict:
        return {k: self.prepare_endpoint(k, v, region) for k, v in endpoints.items()}

    def choose_manifest(self, manifest: dict, cdn=None):
        """Get manifest URL for the title based on CDN weight (or specified CDN)."""
        if cdn:
            cdn = cdn.lower()
            manifest = next((x for x in manifest["audioVideoUrls"]["avCdnUrlSets"] if x["cdn"].lower() == cdn), {})
            if not manifest:
                raise self.log.exit(f" - There isn't any DASH manifests available on the CDN \"{cdn}\" for this title")
        else:
            manifest = next((x for x in sorted([x for x in manifest["audioVideoUrls"]["avCdnUrlSets"]], key=lambda x: int(x["cdnWeightsRank"]))), {})

        return manifest

    def get_manifest(
        self, title: Title, video_codec: str, bitrate_mode: str, quality: str, hdr=None,
            ignore_errors: bool = False
    ) -> dict:
        res = self.session.get(
            url=self.endpoints["playback"],
            params={
                "asin": title.id,
                "consumptionType": "Streaming",
                "desiredResources": ",".join([
                    "PlaybackUrls",
                    "AudioVideoUrls",
                    "CatalogMetadata",
                    "ForcedNarratives",
                    "SubtitlePresets",
                    "SubtitleUrls",
                    "TransitionTimecodes",
                    "TrickplayUrls",
                    "CuepointPlaylist",
                    "XRayMetadata",
                    "PlaybackSettings",
                ]),
                "deviceID": self.device_id,
                "deviceTypeID": self.device["device_type"],
                "firmware": 1,
                "gascEnabled": str(self.pv).lower(),
                "marketplaceID": self.region["marketplace_id"],
                "resourceUsage": "CacheResources",
                "videoMaterialType": "Feature",
                "playerType": "html5",
                "clientId": self.client_id,
                **({
                    "operatingSystemName": "Linux" if quality == "SD" else "Windows",
                    "operatingSystemVersion": "unknown" if quality == "SD" else "10.0",
                } if not self.device_token else {}),
                "deviceDrmOverride": "CENC",
                "deviceStreamingTechnologyOverride": "DASH", # or SmoothStreaming
                "deviceProtocolOverride": "Https",
                "deviceVideoCodecOverride": video_codec,
                "deviceBitrateAdaptationsOverride": bitrate_mode.replace("+", ","),
                "deviceVideoQualityOverride": quality,
                "deviceHdrFormatsOverride": self.VIDEO_RANGE_MAP.get(hdr, "None"),
                "supportedDRMKeyScheme": "DUAL_KEY",  # ?
                "liveManifestType": "live,accumulating",  # ?
                "titleDecorationScheme": "primary-content",
                "subtitleFormat": "TTMLv2",
                "languageFeature": "MLFv2",  # ?
                "uxLocale": "en_US",
                "xrayDeviceClass": "normal",
                "xrayPlaybackMode": "playback",
                "xrayToken": "XRAY_WEB_2020_V1",
                "playbackSettingsFormatVersion": "1.0.0",
                "playerAttributes": json.dumps({"frameRate": "HFR"}),
                # possibly old/unused/does nothing:
                "audioTrackId": "all",
            },
            headers={
                "Authorization": f"Bearer {self.device_token}" if self.device_token else None,
            },
        )
        try:
            manifest = res.json()
        except json.JSONDecodeError:
            if ignore_errors:
                return {}

            raise self.log.exit(" - Amazon didn't return JSON data when obtaining the Playback Manifest.")

        if "error" in manifest:
            if ignore_errors:
                return {}
            raise self.log.exit(" - Amazon reported an error when obtaining the Playback Manifest.")

        # Commented out as we move the rights exception check elsewhere
        # if "rightsException" in manifest["returnedTitleRendition"]["selectedEntitlement"]:
        #     if ignore_errors:
        #         return {}
        #     raise self.log.exit(" - The profile used does not have the rights to this title.")

        # Below checks ignore NoRights errors

        if (
          manifest.get("errorsByResource", {}).get("PlaybackUrls") and
          manifest["errorsByResource"]["PlaybackUrls"].get("errorCode") != "PRS.NoRights.NotOwned"
        ):
            if ignore_errors:
                return {}
            error = manifest["errorsByResource"]["PlaybackUrls"]
            raise self.log.exit(f" - Amazon had an error with the Playback Urls: {error['message']} [{error['errorCode']}]")

        if (
          manifest.get("errorsByResource", {}).get("AudioVideoUrls") and
          manifest["errorsByResource"]["AudioVideoUrls"].get("errorCode") != "PRS.NoRights.NotOwned"
        ):
            if ignore_errors:
                return {}
            error = manifest["errorsByResource"]["AudioVideoUrls"]
            raise self.log.exit(f" - Amazon had an error with the A/V Urls: {error['message']} [{error['errorCode']}]")

        return manifest

    @staticmethod
    def get_original_language(manifest):
        """Get a title's original language from manifest data."""
        try:
            return next(
                x["language"].replace("_", "-")
                for x in manifest["catalogMetadata"]["playback"]["audioTracks"]
                if x["isOriginalLanguage"]
            )
        except (KeyError, StopIteration):
            pass

        if "defaultAudioTrackId" in manifest.get("playbackUrls", {}):
            try:
                return manifest["playbackUrls"]["defaultAudioTrackId"].split("_")[0]
            except IndexError:
                pass

        try:
            return sorted(
                manifest["audioVideoUrls"]["audioTrackMetadata"],
                key=lambda x: x["index"]
            )[0]["languageCode"]
        except (KeyError, IndexError):
            pass

        return None

    def clean_mpd_url(self, mpd_url, optimise=True):
        #self.log.debug(f"MPD URL: {mpd_url}, optimise: {optimise}")
        """Clean up an Amazon MPD manifest url."""
        if 'akamaihd.net' in mpd_url:
            match = re.search(r'[^/]*\$[^/]*/', mpd_url)
            if match:
                dollar_sign_part = match.group(0)
                mpd_url = mpd_url.replace(dollar_sign_part, '', 1)
                return mpd_url
        
        if optimise:
            return mpd_url.replace("~", "") + "?encoding=segmentBase"
        else:
            if match :=   re.match(r"(https?://.*/)d.?/.*~/(.*)", mpd_url):
                self.log.debug(f"returned: {''.join(match.groups())}")
                return "".join(match.groups())
            elif match := re.match(r"(https?://.*/)d.?/.*\$.*?/(.*)", mpd_url):
                self.log.debug(f"returned: {''.join(match.groups())}")
                return "".join(match.groups())
            elif match := re.match(r"(https?://.*/).*\$.*?/(.*)", mpd_url):
                self.log.debug(f"returned: {''.join(match.groups())}")
                return "".join(match.groups())
            elif match := re.split(r"(?i)(/)", mpd_url)[:5] + re.split(r"(?i)(/)", mpd_url)[9:]:
                self.log.debug(f"returned: {''.join(match.groups())}")
                return "".join(match.groups())
            raise ValueError("Unable to parse MPD URL")

        
        
    def get_best_quality(self, title):
        """
        Choose the best quality manifest from CBR / CVBR
        """

        track_list = []
        bitrates = [self.orig_bitrate]

        if self.vcodec != "H265":
            bitrates = self.orig_bitrate.split('+')

        for bitrate in bitrates:
            manifest = self.get_manifest(
                title,
                video_codec=self.vcodec,
                bitrate_mode=bitrate,
                quality=self.vquality,
                hdr=self.range,
                ignore_errors=False
            )

            if not manifest:
                self.log.warning(f"Skipping {bitrate} manifest due to error")
                continue
                
            # return three empty objects if a rightsException error exists to correlate to manifest, chosen_manifest, tracks
            if "rightsException" in manifest["returnedTitleRendition"]["selectedEntitlement"]:
                return None, None, None

            self.customer_id = manifest["returnedTitleRendition"]["selectedEntitlement"]["grantedByCustomerId"]

            default_url_set = manifest["playbackUrls"]["urlSets"][manifest["playbackUrls"]["defaultUrlSetId"]]
            encoding_version = default_url_set["urls"]["manifest"]["encodingVersion"]
            self.log.info(f" + Detected encodingVersion={encoding_version}")

            chosen_manifest = self.choose_manifest(manifest, self.cdn)

            if not chosen_manifest:
                self.log.warning(f"No {bitrate} manifests available")
                continue

            mpd_url = self.clean_mpd_url(chosen_manifest["avUrlInfoList"][0]["url"])
            self.log.debug(mpd_url)
            


            if chosen_manifest["streamingTechnology"] == "DASH":
                self.log.info(f" + Downloading {bitrate} MPD")
                tracks = Tracks([
                    x for x in iter(Tracks.from_mpd(
                        url=mpd_url,
                        session=self.session,
                        source=self.ALIASES[0],
                    ))
                ])
            elif chosen_manifest["streamingTechnology"] == "SmoothStreaming":
                self.log.info(f" + Downloading {bitrate} ISM")
                tracks = Tracks([
                    x for x in iter(Tracks.from_ism(
                        url=mpd_url,
                        session=self.session,
                        source=self.ALIASES[0],
                    ))
                ])
            else:
                raise self.log.exit(f"Unsupported manifest type: {chosen_manifest['streamingTechnology']}")

            for video in tracks.videos:
                video.note = bitrate

            max_size = max(tracks.videos, key=lambda x: int(x.size or 0)).size

            track_list.append({
                'bitrate': bitrate,
                'max_size': max_size,
                'manifest': manifest,
                'chosen_manifest': chosen_manifest,
                'tracks': tracks
            })

        best_quality = max(track_list, key=lambda x: x['max_size'])

        if len(self.bitrate.split('+')) > 1:
            self.bitrate = best_quality['bitrate']
            self.log.info("Selected video manifest bitrate: %s", best_quality['bitrate'])

        return best_quality['manifest'], best_quality['chosen_manifest'], best_quality['tracks']

    # Service specific classes

    class DeviceRegistration:

        def __init__(self, device: dict, endpoints: dict, cache_path: Path, session: requests.Session, log: Logger):
            self.session = session
            self.device = device
            self.endpoints = endpoints
            self.cache_path = cache_path
            self.log = log

            self.device = {k: str(v) if not isinstance(v, str) else v for k, v in self.device.items()}

            self.bearer = None
            if os.path.isfile(self.cache_path):
                with open(self.cache_path, encoding="utf-8") as fd:
                    cache = jsonpickle.decode(fd.read())
                #self.device["device_serial"] = cache["device_serial"]
                if cache.get("expires_in", 0) > int(time.time()):
                    # not expired, lets use
                    self.log.info(" + Using cached device bearer")
                    self.bearer = cache["access_token"]
                else:
                    # expired, refresh
                    self.log.info("Cached device bearer expired, refreshing...")
                    refreshed_tokens = self.refresh(self.device, cache["refresh_token"])
                    refreshed_tokens["refresh_token"] = cache["refresh_token"]
                    # expires_in seems to be in minutes, create a unix timestamp and add the minutes in seconds
                    refreshed_tokens["expires_in"] = int(time.time()) + int(refreshed_tokens["expires_in"])
                    with open(self.cache_path, "w", encoding="utf-8") as fd:
                        fd.write(jsonpickle.encode(refreshed_tokens))
                    self.bearer = refreshed_tokens["access_token"]
            else:
                self.log.info(" + Registering new device bearer")
                self.bearer = self.register(self.device)

        def register(self, device: dict) -> dict:
            """
            Register device to the account
            :param device: Device data to register
            :return: Device bearer tokens
            """
            # OnTV csrf
            csrf_token = self.get_csrf_token()

            # Code pair
            code_pair = self.get_code_pair(device)

            # Device link
            response = self.session.post(
                url=self.endpoints["devicelink"],
                headers={
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.9,es-US;q=0.8,es;q=0.7",  # needed?
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": self.endpoints["ontv"]
                },
                params=urlencode({
                    # any reason it urlencodes here? requests can take a param dict...
                    "ref_": "atv_set_rd_reg",
                    "publicCode": code_pair["public_code"],  # public code pair
                    "token": csrf_token  # csrf token
                })
            )
            if response.status_code != 200:
                raise self.log.exit(f"Unexpected response with the codeBasedLinking request: {response.text} [{response.status_code}]")

            # Register
            response = self.session.post(
                url=self.endpoints["register"],
                headers={
                    "Content-Type": "application/json",
                    "Accept-Language": "en-US"
                },
                json={
                    "auth_data": {
                        "code_pair": code_pair
                    },
                    "registration_data": device,
                    "requested_token_type": ["bearer"],
                    "requested_extensions": ["device_info", "customer_info"]
                },
                cookies=None  # for some reason, may fail if cookies are present. Odd.
            )
            if response.status_code != 200:
                raise self.log.exit(f"Unable to register: {response.text} [{response.status_code}]")
            bearer = response.json()["response"]["success"]["tokens"]["bearer"]
            bearer["expires_in"] = int(time.time()) + int(bearer["expires_in"])

            # Cache bearer
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as fd:
                fd.write(jsonpickle.encode(bearer))

            return bearer["access_token"]

        def refresh(self, device: dict, refresh_token: str) -> dict:
            response = self.session.post(
                url=self.endpoints["token"],
                json={
                    "app_name": device["app_name"],
                    "app_version": device["app_version"],
                    "source_token_type": "refresh_token",
                    "source_token": refresh_token,
                    "requested_token_type": "access_token"
                }
            ).json()
            if "error" in response:
                self.cache_path.unlink(missing_ok=True)  # Remove the cached device as its tokens have expired
                raise self.log.exit(
                    f"Failed to refresh device token: {response['error_description']} [{response['error']}]"
                )
            if response["token_type"] != "bearer":
                raise self.log.exit("Unexpected returned refreshed token type")
            return response

        def get_csrf_token(self) -> str:
            """
            On the amazon website, you need a token that is in the html page,
            this token is used to register the device
            :return: OnTV Page's CSRF Token
            """
            res = self.session.get(self.endpoints["ontv"])
            response = res.text
            if 'input type="hidden" name="appAction" value="SIGNIN"' in response:
                raise self.log.exit(
                    "Cookies are signed out, cannot get ontv CSRF token. "
                    f"Expecting profile to have cookies for: {self.endpoints['ontv']}"
                )
            for match in re.finditer(r"<script type=\"text/template\">(.+)</script>", response):
                prop = json.loads(match.group(1))
                prop = prop.get("props", {}).get("codeEntry", {}).get("token")
                if prop:
                    return prop
            raise self.log.exit("Unable to get ontv CSRF token \n Navigate to /region/eu/ontv/code?ref_=atv_auth_red_aft, login and save cookies from that page to default.txt")

        def get_code_pair(self, device: dict) -> dict:
            """
            Getting code pairs based on the device that you are using
            :return: public and private code pairs
            """
            res = self.session.post(
                url=self.endpoints["codepair"],
                headers={
                    "Content-Type": "application/json",
                    "Accept-Language": "en-US"
                },
                json={"code_data": device}
            ).json()
            if "error" in res:
                raise self.log.exit(f"Unable to get code pair: {res['error_description']} [{res['error']}]")
            return res
