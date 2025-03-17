import base64
import json
import os
import re
import sys
import time
from datetime import timedelta

import click
import jsonpickle
import requests
from langcodes import Language

from vinetrimmer.objects import AudioTrack, MenuTrack, TextTrack, Title, Tracks, VideoTrack
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils.collections import as_list, flatten
from vinetrimmer.utils.MSL import MSL
from vinetrimmer.utils.MSL.schemes import KeyExchangeSchemes
from vinetrimmer.utils.MSL.schemes.UserAuthentication import UserAuthentication
from vinetrimmer.utils.widevine.device import LocalDevice
from vinetrimmer.vendor.pymp4.parser import Box
from vinetrimmer.utils.gen_esn import chrome_esn_generator

class Netflix(BaseService):
    """
    Service code for the Netflix streaming service (https://netflix.com).

    \b
    Authorization: Cookies if ChromeCDM, Cookies + Credentials otherwise.
    Security: UHD@L1 HD@L3*, heavily monitors UHD, but doesn't seem to care about <= FHD.

    *MPL: FHD with Android L3, sporadically available with ChromeCDM
     HPL: 1080p with ChromeCDM, 720p/1080p with other L3 (varies per title)

    \b
    Tips: - The library of contents as well as regional availability is available at https://unogs.com
            However, Do note that Netflix locked everyone out of being able to automate the available data
            meaning the reliability and amount of information may be reduced.
          - You could combine the information from https://unogs.com with https://justwatch.com for further data
          - The ESN you choose is important to match the CDM you provide
          - Need 4K manifests? Try use an Nvidia Shield-based ESN with the system ID changed to yours. The "shield"
            term gives it 4K, and the system ID passes the key exchange verifications as it matches your CDM. They
            essentially don't check if the device is actually a Shield by the verified system ID.
          - ESNs capable of 4K manifests can provide HFR streams for everything other than H264. Other ESNs can
            seemingly get HFR from the VP9 P2 profile or higher. I don't think H264 ever gets HFR.

    TODO: Implement the MSL v2 API response's `crop_x` and `crop_y` values with Matroska's cropping metadata
    """

    ALIASES = ["NF", "netflix"]
    #GEOFENCE = ['us']
    TITLE_RE = [
        r"^(?:https?://(?:www\.)?netflix\.com(?:/[a-z0-9]{2})?/(?:title/|watch/|.+jbv=))?(?P<id>\d+)",
        r"^https?://(?:www\.)?unogs\.com/title/(?P<id>\d+)",
    ]

    NF_LANG_MAP = {
        "es": "es-419",
        "pt": "pt-PT",
    }

    @staticmethod
    @click.command(name="Netflix", short_help="https://netflix.com")
    @click.argument("title", type=str, required=False)
    @click.option("-p", "--profile", type=click.Choice(["MPL", "HPL", "QC", "MPL+HPL", "MPL+HPL+QC", "MPL+QC"], case_sensitive=False),
                  default="MPL+HPL+QC",
                  help="H.264 profile to use. Default is best available.")
    @click.option("--meta-lang", type=str, help="Language to use for metadata")
    @click.option("--single", is_flag=True, default=False, help="Single title mode. Must use for trailers.")
    @click.pass_context
    def cli(ctx, **kwargs):
        return Netflix(ctx, **kwargs)

    def __init__(self, ctx, title, profile, meta_lang, single):
        super().__init__(ctx)
        self.parse_title(ctx, title)
        self.profile = profile
        self.meta_lang = meta_lang
        self.single = single

        if ctx.parent.params["proxy"] and len("".join(i for i in ctx.parent.params["proxy"] if not i.isdigit())) == 2:
            self.GEOFENCE.append(ctx.parent.params["proxy"])

        self.vcodec = ctx.parent.params["vcodec"]
        self.acodec = ctx.parent.params["acodec"]
        self.range = ctx.parent.params["range_"]
        self.quality = ctx.parent.params["quality"]
        self.audio_only = ctx.parent.params["audio_only"]
        self.subs_only = ctx.parent.params["subs_only"]
        self.chapters_only = ctx.parent.params["chapters_only"]

        self.cdm = ctx.obj.cdm

        # General
        self.download_proxied = len(self.GEOFENCE) > 0  # needed if the title is unavailable at home IP
        self.profiles = []

        # MSL
        self.msl = None
        self.esn = None
        self.userauthdata = None

        # Web API values
        self.react_context = {}

        # DRM/Manifest values
        self.session_id = None

        self.configure()

    def get_titles(self):
        metadata = self.get_metadata(self.title)["video"]
        if metadata["type"] == "movie" or self.single:
            titles = [Title(
                id_=self.title,
                type_=Title.Types.MOVIE,
                name=metadata["title"],
                year=metadata["year"],
                source=self.ALIASES[0],
                service_data=metadata
            )]
        else:
            episodes = [episode for season in [
                [dict(x, **{"season": season["seq"]}) for x in season["episodes"]]
                for season in metadata["seasons"]
            ] for episode in season]
            titles = [Title(
                id_=self.title,
                type_=Title.Types.TV,
                name=metadata["title"],
                season=episode.get("season"),
                episode=episode.get("seq"),
                episode_name=episode.get("title"),
                source=self.ALIASES[0],
                service_data=episode
            ) for episode in episodes]

        # TODO: Get original language without making an extra manifest request
        self.log.warning("HEVC PROFILES for the first title sometimes FAIL with Validation error so we use H264 HPL as a first trial, if it does not exist, we try H264 MPL")
        try:
            manifest = self.get_manifest(titles[0], self.profiles)
        except:
            try:
                manifest = self.get_manifest(titles[0], self.config["profiles"]["video"]["H264"]["HPL"])
            except:
                manifest = self.get_manifest(titles[0], self.config["profiles"]["video"]["H264"]["MPL"])
               
            
        original_language = self.get_original_language(manifest)

        for title in titles:
            
            title.original_lang = original_language

        return titles

    def get_tracks(self, title):
        if self.vcodec == "H264":
            # If H.264, get both MPL and HPL tracks as they alternate in terms of bitrate
            tracks = Tracks()

            self.config["profiles"]["video"]["H264"]["MPL+HPL+QC"] = (
                self.config["profiles"]["video"]["H264"]["MPL"] + self.config["profiles"]["video"]["H264"]["HPL"] + self.config["profiles"]["video"]["H264"]["QC"]
            )

            if self.audio_only or self.subs_only or self.chapters_only:
                profiles = ["MPL+HPL+QC"]
            else:
                profiles = self.profile.split("+")

            for profile in profiles:
                try:
                    manifest = self.get_manifest(title, self.config["profiles"]["video"]["H264"][profile])
                except:
                    manifest = self.get_manifest(title, self.config["profiles"]["video"]["H264"]["MPL"] + self.config["profiles"]["video"]["H264"]["HPL"])
                manifest_tracks = self.manifest_as_tracks(manifest)
                license_url = manifest["links"]["license"]["href"]


                if self.cdm.device.security_level == 3 and self.cdm.device.type == LocalDevice.Types.ANDROID:
                    max_quality = max(x.height for x in manifest_tracks.videos)
                    if profile == "MPL" and max_quality >= 720:
                        manifest_sd = self.get_manifest(title, self.config["profiles"]["video"]["H264"]["BPL"])
                        license_url_sd = manifest_sd["links"]["license"]["href"]
                        if "SD_LADDER" in manifest_sd["video_tracks"][0]["streams"][0]["tags"]:
                            # SD manifest is new encode encrypted with different keys that won't work for HD
                            continue
                        license_url = license_url_sd
                    if profile == "HPL" and max_quality >= 1080:
                        if "SEGMENT_MAP_2KEY" in manifest["video_tracks"][0]["streams"][0]["tags"]:
                            # 1080p license restricted from Android L3, 720p license will work for 1080p
                            manifest_720 = self.get_manifest(
                                title, [x for x in self.config["profiles"]["video"]["H264"]["HPL"] if "l40" not in x]
                            )
                            license_url = manifest_720["links"]["license"]["href"]
                        else:
                            # Older encode, can't use 720p keys for 1080p
                            continue

                for track in manifest_tracks:
                    if track.encrypted:
                        track.extra["license_url"] = license_url
                tracks.add(manifest_tracks, warn_only=True)
            return tracks
            
        elif self.vcodec == "H265":
            # If H.264, get both MPL and HPL tracks as they alternate in terms of bitrate
            tracks = Tracks()
            
            if self.range == "SDR":
                self.profile = "SDR_DO+SDR_CENC"

                self.config["profiles"]["video"]["H265"]["SDR_DO+SDR_CENC"] = (
                    self.config["profiles"]["video"]["H265"]["SDR_DO"] + self.config["profiles"]["video"]["H265"]["SDR_CENC"] 
                )
            elif self.range == "HDR10":
            
                self.profile = "HDR10_DO+HDR10_CENC"

                self.config["profiles"]["video"]["H265"]["HDR10_DO+HDR10_CENC"] = (
                    self.config["profiles"]["video"]["H265"]["HDR10_DO"] + self.config["profiles"]["video"]["H265"]["HDR10_CENC"] 
                )
            else:
               self.log.error("Dolby Vision is not supported yes")
               sys.exit(1)


            profiles = self.profile.split("+")
            self.log.debug(profiles)

            for profile in profiles:
                manifest = self.get_manifest(title, self.config["profiles"]["video"]["H265"][profile])
               
                manifest_tracks = self.manifest_as_tracks(manifest)
                license_url = manifest["links"]["license"]["href"]

                for track in manifest_tracks:
                    if track.encrypted:
                        track.extra["license_url"] = license_url
                tracks.add(manifest_tracks, warn_only=True)
            return tracks
        else:
            manifest = self.get_manifest(title, self.profiles)
            manifest_tracks = self.manifest_as_tracks(manifest)
            license_url = manifest["links"]["license"]["href"]
            for track in manifest_tracks:
                if track.encrypted:
                    track.extra["license_url"] = license_url
                if isinstance(track, VideoTrack):
                    # TODO: Needs something better than this
                    track.hdr10 = track.codec.split("-")[1] == "hdr"  # hevc-hdr, vp9-hdr
                    track.dv = track.codec.startswith("hevc-dv")
            return manifest_tracks

    def get_chapters(self, title):
        metadata = self.get_metadata(title.id)["video"]

        if metadata["type"] == "movie" or self.single:
            episode = metadata
        else:
            season = next(x for x in metadata["seasons"] if x["seq"] == title.season)
            episode = next(x for x in season["episodes"] if x["seq"] == title.episode)

        if not (episode.get("skipMarkers") and episode.get("creditsOffset")):
            return []

        chapters = {}
        for item in episode["skipMarkers"]:
            chapters[item] = {"start": 0, "end": 0}
            if not episode["skipMarkers"][item]:
                continue
            if episode["skipMarkers"][item]["start"] is None:
                chapters[item]["start"] = 0
            else:
                chapters[item]["start"] = (episode["skipMarkers"][item]["start"] / 1000)
            if episode["skipMarkers"][item]["end"] is None:
                chapters[item]["end"] = 0
            else:
                chapters[item]["end"] = (episode["skipMarkers"][item]["end"] / 1000)

        cc, intro = 1, 0
        chaps = [MenuTrack(
            number=1,
            title=f"Part {cc:02}",
            timecode="0:00:00.000",
        )]

        for item in chapters:
            if chapters[item]["start"] != 0:
                if intro == 0:
                    cc += 1
                    chaps.append(MenuTrack(
                        number=cc,
                        title="Intro",
                        timecode=(str(timedelta(seconds=int(chapters[item]["start"] - 1))) + ".500")[:11],
                    ))
                    cc += 1
                    chaps.append(MenuTrack(
                        number=cc,
                        title=f"Part {(cc - 1):02}",
                        timecode=(str(timedelta(seconds=int(chapters[item]["end"]))) + ".250")[:11],
                    ))
                else:
                    cc += 1
                    chaps.append(MenuTrack(
                        number=cc,
                        title=f"Part {cc:02}",
                        timecode=(str(timedelta(seconds=int(chapters[item]["start"] - 1))) + ".500")[:11],
                    ))
                    cc += 1
                    chaps.append(MenuTrack(
                        number=cc,
                        title=f"Part {cc:02}",
                        timecode=(str(timedelta(seconds=int(chapters[item]["end"]))) + ".250")[:11],
                    ))
                    cc += 1

        if cc == 1:
            chaps.append(MenuTrack(
                number=2,
                title="Credits",
                timecode=(str(timedelta(seconds=int(episode["creditsOffset"] - 1))) + ".450")[:11],
            ))
        else:
            chaps.append(MenuTrack(
                number=cc,
                title="Credits",
                timecode=(str(timedelta(seconds=int(episode["creditsOffset"] - 1))) + ".450")[:11],
            ))

        return chaps

    def certificate(self, **_):
        return self.config["certificate"]

    def license(self, challenge, track, session_id, **_):
        if not self.msl:
            raise self.log.exit(" - Cannot get license, MSL client has not been created yet.")
        header, payload_data = self.msl.send_message(
            endpoint=self.config["endpoints"]["licence"],
            params={},
            application_data={
                "version": 2,
                "url": track.extra["license_url"],
                "id": int(time.time() * 10000),
                "esn": self.esn,
                "languages": ["en-US"],
                "uiVersion": self.react_context["serverDefs"]["data"]["uiVersion"],
                "clientVersion": "6.0026.291.011",
                "params": [{
                    "sessionId": base64.b64encode(session_id).decode("utf-8"),
                    "clientTime": int(time.time()),
                    "challengeBase64": base64.b64encode(challenge).decode("utf-8"),
                    "xid": str(int((int(time.time()) + 0.1612) * 1000)),
                }],
                "echo": "sessionId"
            },
            userauthdata=self.userauthdata
        )
        if not payload_data:
            raise self.log.exit(f" - Failed to get license: {header['message']} [{header['code']}]")
        if "error" in payload_data[0]:
            error = payload_data[0]["error"]
            error_display = error.get("display")
            error_detail = re.sub(r" \(E3-[^)]+\)", "", error.get("detail", ""))

            if error_display:
                self.log.critical(f" - {error_display}")
            if error_detail:
                self.log.critical(f" - {error_detail}")

            if not (error_display or error_detail):
                self.log.critical(f" - {error}")

            sys.exit(1)

        return payload_data[0]["licenseResponseBase64"]

    # Service specific functions

    def configure(self):
        self.session.headers.update({"Origin": "https://netflix.com"})
        self.profiles = self.get_profiles()
        self.log.info("Initializing a Netflix MSL client")
        # Grab ESN based on CDM from secrets if no ESN argument provided
        if (self.cdm.device.type == LocalDevice.Types.CHROME if "common_privacy_cert" in dir(self.cdm) else False):  # ESN GENERATOR FOR CHROME
            self.esn = chrome_esn_generator()
        elif "group_certificate" in dir(self.cdm):
            self.esn = edge_esn_generator()
        else:
            sel.log.info(self.config)
            esn_map = self.config.get("esn_map", {})
            self.log.info(esn_map)
            self.esn = esn_map.get(self.cdm.device.system_id) or esn_map.get(str(self.cdm.device.system_id))
        if not self.esn:
            raise self.log.exit(" - No ESN specified")
        self.log.info(f" + ESN: {self.esn}")
        scheme = {
            LocalDevice.Types.CHROME: KeyExchangeSchemes.AsymmetricWrapped,
            LocalDevice.Types.ANDROID: KeyExchangeSchemes.Widevine
        }[self.cdm.device.type]
        self.log.info(f" + Scheme: {scheme}")
        self.msl = MSL.handshake(
            scheme=scheme,
            session=self.session,
            endpoint=self.config["endpoints"]["manifest"],
            sender=self.esn,
            cdm=self.cdm,
            msl_keys_path=self.get_cache("msl_{id}_{esn}_{scheme}.json".format(
                id=self.cdm.device.system_id,
                esn=self.esn,
                scheme=scheme
            ))
        )
        if not self.session.cookies:
            raise self.log.exit(" - No cookies provided, cannot log in.")
        if self.cdm.device.type == LocalDevice.Types.CHROME:
            self.userauthdata = UserAuthentication.NetflixIDCookies(
                netflixid=self.session.cookies.get_dict()["NetflixId"],
                securenetflixid=self.session.cookies.get_dict()["SecureNetflixId"]
            )
        else:
            if not self.credentials:
                raise self.log.exit(" - Credentials are required for Android CDMs, and none were provided.")
            # need to get cookies via an android-like way
            # outdated
            # self.android_login(credentials.username, credentials.password)
            # need to use EmailPassword for userauthdata, it specifically checks for this
            self.userauthdata = UserAuthentication.EmailPassword(
                email=self.credentials.username,
                password=self.credentials.password
            )
        self.react_context = self.get_react_context()

    def get_profiles(self):
        if self.range in ("HDR10", "DV") and self.vcodec not in ("H265", "VP9"):
            self.vcodec = "H265"
        profiles = self.config["profiles"]["video"][self.vcodec]
        if self.range and self.range in profiles:
            return profiles[self.range]
        return profiles

    def get_react_context(self):
        """
        Netflix uses a "BUILD_IDENTIFIER" value on some API's, e.g. the Shakti (metadata) API.
        This value isn't given to the user through normal means so REGEX is needed.
        It's obtained by grabbing the body of a logged-in netflix homepage.
        The value changes often but doesn't often matter if it's only a bit out of date.

        It also uses a Client Version for various MPL calls.

        :returns: reactContext parsed json-loaded dictionary
        """
        cache_loc = self.get_cache("web_data.json")

        if not os.path.isfile(cache_loc):
            headers = {
            'accept': '*/*',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty',
            'origin': 'https://www.netflix.com',
            'connection': 'keep-alive',
            'accept-encoding': 'gzip, deflate, br',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'no-cache',
            'sec-ch-ua': '"Microsoft Edge";v="116", "Chromium";v="116", "Not-A.Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.46'
        }
             
            src = self.session.get("https://www.netflix.com/browse", headers=headers).text
            match = re.search(r"netflix\.reactContext = ({.+});</script><script>window\.", src, re.MULTILINE)
            if not match:
                raise self.log.exit(" - Failed to retrieve reactContext data, cookies might be outdated.")
            react_context_raw = match.group(1)
            react_context = json.loads(re.sub(r"\\x", r"\\u00", react_context_raw))["models"]
            react_context["requestHeaders"]["data"] = {
                re.sub(r"\B([A-Z])", r"-\1", k): str(v) for k, v in react_context["requestHeaders"]["data"].items()
            }
            react_context["abContext"]["data"]["headers"] = {
                k: str(v) for k, v in react_context["abContext"]["data"]["headers"].items()
            }
            react_context["requestHeaders"]["data"] = {
                k: str(v) for k, v in react_context["requestHeaders"]["data"].items()
            }
            #react_context["playerModel"]["data"]["config"]["core"]["initParams"]["clientVersion"] = (
            #    react_context["playerModel"]["data"]["config"]["core"]["assets"]["core"].split("-")[-1][:-3]
            #)

            os.makedirs(os.path.dirname(cache_loc), exist_ok=True)
            with open(cache_loc, "w", encoding="utf-8") as fd:
                fd.write(jsonpickle.encode(react_context))

            return react_context

        with open(cache_loc, encoding="utf-8") as fd:
            return jsonpickle.decode(fd.read())

    def get_metadata(self, title_id):
        """
        Obtain Metadata information about a title by it's ID.
        :param title_id: Title's ID.
        :returns: Title Metadata.
        """

        """
        # Wip non-working code for the newer shakti metadata replacement
        metadata = self.session.post(
            url=self.config["endpoints"]["website"].format(
                build_id=self.react_context["serverDefs"]["data"]["BUILD_IDENTIFIER"]
            ),
            params={
                # features
                "webp": self.react_context["browserInfo"]["data"]["features"]["webp"],
                "drmSystem": self.config["configuration"]["drm_system"],
                # truths
                "isVolatileBillboardsEnabled": self.react_context["truths"]["data"]["volatileBillboardsEnabled"],
                "routeAPIRequestsThroughFTL": self.react_context["truths"]["data"]["routeAPIRequestsThroughFTL"],
                "isTop10Supported": self.react_context["truths"]["data"]["isTop10Supported"],
                "categoryCraversEnabled": self.react_context["truths"]["data"]["categoryCraversEnabled"],
                "hasVideoMerchInBob": self.react_context["truths"]["data"]["hasVideoMerchInBob"],
                "persoInfoDensity": self.react_context["truths"]["data"]["enablePersoInfoDensityToggle"],
                "contextAwareImages": self.react_context["truths"]["data"]["contextAwareImages"],
                # ?
                "falcor_server": "0.1.0",
                "withSize": True,
                "materialize": True,
                "original_path": quote_plus(
                    f"/shakti/{self.react_context['serverDefs']['data']['BUILD_IDENTIFIER']}/pathEvaluator"
                )
            },
            headers=dict(
                **self.react_context["abContext"]["data"]["headers"],
                **{
                    "X-Netflix.Client.Request.Name": "ui/falcorUnclassified",
                    "X-Netflix.esn": self.react_context["esnGeneratorModel"]["data"]["esn"],
                    "x-netflix.nq.stack": self.react_context["serverDefs"]["data"]["stack"],
                    "x-netflix.request.client.user.guid": (
                        self.react_context["memberContext"]["data"]["userInfo"]["guid"]
                    )
                },
                **self.react_context["requestHeaders"]["data"]
            ),
            data={
                "path": json.dumps([
                    [
                        "videos",
                        70155547,
                        [
                            "bobSupplementalMessage",
                            "bobSupplementalMessageIcon",
                            "bookmarkPosition",
                            "delivery",
                            "displayRuntime",
                            "evidence",
                            "hasSensitiveMetadata",
                            "interactiveBookmark",
                            "maturity",
                            "numSeasonsLabel",
                            "promoVideo",
                            "releaseYear",
                            "seasonCount",
                            "title",
                            "userRating",
                            "userRatingRequestId",
                            "watched"
                        ]
                    ],
                    [
                        "videos",
                        70155547,
                        "seasonList",
                        "current",
                        "summary"
                    ]
                ]),
                "authURL": self.react_context["memberContext"]["data"]["userInfo"]["authURL"]
            }
        )

        print(metadata.headers)
        print(metadata.text)
        exit()
        """

        try:
            metadata = self.session.get(
                self.config["endpoints"]["metadata"].format(build_id=self.react_context['serverDefs']['data']['BUILD_IDENTIFIER']),
                params={
                    "movieid": title_id,
                    "drmSystem": self.config["configuration"]["drm_system"],
                    "isWatchlistEnabled": False,
                    "isShortformEnabled": False,
                    "isVolatileBillboardsEnabled": self.react_context["truths"]["data"]["volatileBillboardsEnabled"],
                    "languages": self.meta_lang
                }
            ).json()
        except requests.HTTPError as e:
            if e.response.status_code == 500:
                self.log.warning(
                    " - Recieved a HTTP 500 error while getting metadata, deleting cached reactContext data"
                )
                os.unlink(self.get_cache("web_data.json"))
                return self.get_metadata(self, title_id)
            raise
        except json.JSONDecodeError:
            raise self.log.exit(" - Failed to get metadata, title might not be available in your region.")
        else:
            if "status" in metadata and metadata["status"] == "error":
                raise self.log.exit(
                    f" - Failed to get metadata, cookies might be expired. ({metadata['message']})"
                )
            return metadata

    def get_manifest(self, title, video_profiles):
        if isinstance(video_profiles, dict):
            video_profiles = list(video_profiles.values())
        if self.quality == 720:
            # NF only returns lower quality 720p streams if 1080p is also requested
            video_profiles = [x for x in video_profiles if "l40" not in x]
        audio_profiles = self.config["profiles"]["audio"]
        if self.acodec:
            audio_profiles = audio_profiles[self.acodec]
        if isinstance(audio_profiles, dict):
            audio_profiles = list(audio_profiles.values())
        profiles = sorted(set(flatten(as_list(
            # as list then flatten in case any of these profiles are a list of lists
            # list(set()) used to remove any potential duplicates
            self.config["profiles"]["video"]["H264"]["BPL"],  # always required for some reason
            video_profiles,
            audio_profiles,
            self.config["profiles"]["subtitles"],
        ))))
        self.log.debug("Profiles:\n\t" + "\n\t".join(profiles))

        params = {}
        if (self.cdm.device.type == LocalDevice.Types.CHROME if "common_privacy_cert" in dir(self.cdm) else False):
            params = {
                "reqAttempt": 1,
                "reqPriority": 0,
                "reqName": "prefetch/manifest",
                "clienttype": "akira",
                }
            
        manifest_data = {
            'version': 2,
            'url': '/manifest',
            "id": int(time.time()),
             "esn": self.esn,
            'languages': ['en-US'],
            'uiVersion': 'shakti-va3fd86e3',
            'clientVersion': '6.0041.930.911',
            'params':{'type': 'standard',
                    'viewableId': title.service_data.get("episodeId", title.service_data["id"]),
                    'profiles': profiles,
                    'flavor': 'STANDARD',
                    "drmType": self.config["configuration"]["drm_system"],
                    "drmVersion": self.config["configuration"]["drm_version"],
                    'usePsshBox': True,
                    'isBranching': False,
                    'useHttpsStreams': False,
                    'imageSubtitleHeight': 1080,
                    'uiVersion': 'shakti-va3fd86e3',
                    'clientVersion': '6.0041.930.911',
                    'platform': '113.0.1774',
                    'supportsPreReleasePin': True,
                    'supportsWatermark': True,
                    'showAllSubDubTracks': True,
                    'titleSpecificData': {},
                    "videoOutputInfo": [{
                                # todo ; make this return valid, but "secure" values, maybe it helps
                                "type": "DigitalVideoOutputDescriptor",
                                "outputType": "unknown",
                                "supportedHdcpVersions": self.config["configuration"]["supported_hdcp_versions"],
                                "isHdcpEngaged": self.config["configuration"]["is_hdcp_engaged"]
                            }],
                    'preferAssistiveAudio': False,
                    'liveMetadataFormat': 'INDEXED_SEGMENT_TEMPLATE',
                    'isNonMember': False,
                    'osVersion': '10.0',
                    'osName': 'windows',
                    'desiredVmaf': 'plus_lts',
                    'desiredSegmentVmaf': 'plus_lts',
                    'requestSegmentVmaf': False,
                    'challenge': self.config["payload_challenge"],
                    'deviceSecurityLevel': '3000'
                }
           }
           
        self.log.debug(manifest_data)
            
        
        _, payload_chunks = self.msl.send_message(
            endpoint=self.config["endpoints"]["manifest"],
            params=params,
            application_data=manifest_data,
            userauthdata=self.userauthdata
        )
        if "errorDetails" in payload_chunks:
            raise Exception(f"Manifest call failed: {payload_chunks['errorDetails']}")
        return payload_chunks

    def manifest_as_tracks(self, manifest):
        # filter audio_tracks so that each stream is an entry instead of each track
        manifest["audio_tracks"] = [x for y in [
            [dict(t, **d) for d in t["streams"]]
            for t in manifest["audio_tracks"]
        ] for x in y]
        return Tracks(
            # VIDEO
            [VideoTrack(
                id_=x["downloadable_id"],
                source=self.ALIASES[0],
                url=x["urls"][0]["url"],
                # metadata
                codec=x["content_profile"],
                bitrate=x["bitrate"] * 1000,
                width=x["res_w"],
                height=x["res_h"],
                fps=(float(x["framerate_value"]) / x["framerate_scale"]) if "framerate_value" in x else None,
                # switches/options
                needs_proxy=self.download_proxied,
                needs_repack=False,
                # decryption
                encrypted=x["isDrm"],
                pssh=Box.parse(base64.b64decode(manifest["video_tracks"][0]["drmHeader"]["bytes"])) if x[
                    "isDrm"] else None,
                kid=x["drmHeaderId"] if x["isDrm"] else None,
            ) for x in manifest["video_tracks"][0]["streams"]],
            # AUDIO
            [AudioTrack(
                id_=x["downloadable_id"],
                source=self.ALIASES[0],
                url=x["urls"][0]["url"],
                # metadata
                codec=x["content_profile"],
                language=self.NF_LANG_MAP.get(x["language"], x["language"]),
                bitrate=x["bitrate"] * 1000,
                channels=x["channels"],
                descriptive=x.get("rawTrackType", "").lower() == "assistive",
                # switches/options
                needs_proxy=self.download_proxied,
                needs_repack=False,
                # decryption
                encrypted=x["isDrm"],
                pssh=Box.parse(base64.b64decode(x["drmHeader"]["bytes"])) if x["isDrm"] else None,
                kid=x.get("drmHeaderId") if x["isDrm"] else None,  # TODO: haven't seen enc audio, needs testing
            ) for x in manifest["audio_tracks"]],
            # SUBTITLE
            [TextTrack(
                id_=list(x["downloadableIds"].values())[0],
                source=self.ALIASES[0],
                url=next(iter(next(iter(x["ttDownloadables"].values()))["downloadUrls"].values())),
                # metadata
                codec=next(iter(x["ttDownloadables"].keys())),
                language=self.NF_LANG_MAP.get(x["language"], x["language"]),
                forced=x["isForcedNarrative"],
                # switches/options
                needs_proxy=self.download_proxied,
                # text track options
                sdh=x["rawTrackType"] == "closedcaptions"
            ) for x in manifest["timedtexttracks"] if not x["isNoneTrack"]]
        )

    @staticmethod
    def get_original_language(manifest):
        for language in manifest["audio_tracks"]:
            if language["languageDescription"].endswith(" [Original]"):
                return Language.get(language["language"])
        # e.g. get `en` from "A:1:1;2;en;0;|V:2:1;[...]"
        return Language.get(manifest["defaultTrackOrderList"][0]["mediaId"].split(";")[2])
