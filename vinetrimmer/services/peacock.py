import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime

import click
import requests

from vinetrimmer.objects import Title, Tracks
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils.regex import find


class Peacock(BaseService):
    """
    Service code for NBC's Peacock streaming service (https://peacocktv.com).

    \b
    Authorization: Cookies
    Security: UHD@-- FHD@L3, doesn't care about releases.

    \b
    Tips: - The library of contents can be viewed without logging in at https://www.peacocktv.com/stream/tv
            See the footer for links to movies, news, etc. A US IP is required to view.
    """

    ALIASES = ["PCOK", "peacock"]
    #GEOFENCE = ["us"]
    TITLE_RE = [
        r"(?:https?://(?:www\.)?peacocktv\.com/watch/asset/|/?)(?P<id>movies/[a-z0-9/./-]+/[a-f0-9-]+)",
        r"(?:https?://(?:www\.)?peacocktv\.com/watch/asset/|/?)(?P<id>tv/[a-z0-9-/.]+/\d+)",
        r"(?:https?://(?:www\.)?peacocktv\.com/watch/asset/|/?)(?P<id>-/[a-z0-9-/.]+/\d+)",
        r"(?:https?://(?:www\.)?peacocktv\.com/stream-tv/)?(?P<id>[a-z0-9-/.]+)",
    ]

    @staticmethod
    @click.command(name="Peacock", short_help="https://peacocktv.com")
    @click.argument("title", type=str, required=False)
    @click.option("-m", "--movie", is_flag=True, default=False, help="Title is a movie.")
    @click.pass_context
    def cli(ctx, **kwargs):
        return Peacock(ctx, **kwargs)

    def __init__(self, ctx, title, movie):
        super().__init__(ctx)
        self.parse_title(ctx, title)
        self.movie = movie

        self.profile = ctx.obj.profile

        self.service_config = None
        self.hmac_key = None
        self.tokens = None
        self.license_api = None
        self.license_bt = None
        self.vcodec = ctx.parent.params["vcodec"]
        self.vrange= ctx.parent.params["range_"]

        self.configure()

    def get_titles(self):
        # Title is a slug, e.g. `/tv/the-office/4902514835143843112` or just `the-office`

        if "/" not in self.title:
            r = self.session.get(self.config["endpoints"]["stream_tv"].format(title_id=self.title))
            self.title = find("/watch/asset(/[^']+)", r.text)
            if not self.title:
                raise self.log.exit(" - Title ID not found or invalid")

        if not self.title.startswith("/"):
            self.title = f"/{self.title}"

        if self.title.startswith("/movies/"):
            self.movie = True

        res = self.session.get(
            url=self.config["endpoints"]["node"],
            params={
                "slug": self.title,
                "represent": "(items(items))"
            },
            headers={
                "Accept": "*",
                "Referer": f"https://www.peacocktv.com/watch/asset{self.title}",
                "X-SkyOTT-Device": self.config["client"]["device"],
                "X-SkyOTT-Platform": self.config["client"]["platform"],
                "X-SkyOTT-Proposition": self.config["client"]["proposition"],
                "X-SkyOTT-Provider": self.config["client"]["provider"],
                "X-SkyOTT-Territory": self.config["client"]["territory"],
                "X-SkyOTT-Language": "en"
            }
        ).json()

        if self.movie:
            return Title(
                id_=self.title,
                type_=Title.Types.MOVIE,
                name=res["attributes"]["title"],
                year=res["attributes"]["year"],
                source=self.ALIASES[0],
                service_data=res,
            )
        else:
            titles = []
            for season in res["relationships"]["items"]["data"]:
                for episode in season["relationships"]["items"]["data"]:
                    titles.append(episode)
            return [Title(
                id_=self.title,
                type_=Title.Types.TV,
                name=res["attributes"]["title"],
                year=x["attributes"].get("year"),
                season=x["attributes"].get("seasonNumber"),
                episode=x["attributes"].get("episodeNumber"),
                episode_name=x["attributes"].get("title"),
                source=self.ALIASES[0],
                service_data=x
            ) for x in titles]

    def get_tracks(self, title):
        supported_colour_spaces=["SDR"]

        if self.vrange == "HDR10":
            self.log.info("Switched dynamic range to  HDR10")
            supported_colour_spaces=["HDR10"]
        if self.vrange == "DV":
            self.log.info("Switched dynamic range to  DV")
            supported_colour_spaces=["DolbyVision"]
        content_id = title.service_data["attributes"]["formats"]["HD"]["contentId"]
        variant_id = title.service_data["attributes"]["providerVariantId"]

        sky_headers = {
            # order of these matter!
            "X-SkyOTT-Agent": ".".join([
                self.config["client"]["proposition"].lower(),
                self.config["client"]["device"].lower(),
                self.config["client"]["platform"].lower()
            ]),
            "X-SkyOTT-PinOverride": "false",
            "X-SkyOTT-Provider": self.config["client"]["provider"],
            "X-SkyOTT-Territory": self.config["client"]["territory"],
            "X-SkyOTT-UserToken": self.tokens["userToken"]
        }

        body = json.dumps({
            "device": {
                # maybe get these from the config endpoint?
                "capabilities": [
                    {
                        "protection": "PLAYREADY",
                        "container": "ISOBMFF",
                        "transport": "DASH",
                        "acodec": "AAC",
                        "vcodec": "H265" if self.vcodec == "H265" else "H264",
                    },
                    {
                        "protection": "NONE",
                        "container": "ISOBMFF",
                        "transport": "DASH",
                        "acodec": "AAC",
                        "vcodec": "H265" if self.vcodec == "H265" else "H264",
                    }
                ],
                "maxVideoFormat": "UHD" if self.vcodec == "H265" else "HD",
                "supportedColourSpaces": supported_colour_spaces,
                "model": self.config["client"]["platform"],
                "hdcpEnabled": "true"
            },
            "client": {
                "thirdParties": ["FREEWHEEL", "YOSPACE"]  # CONVIVA
            },
            "contentId": content_id,
            "providerVariantId": variant_id,
            "parentalControlPin": "null"
        }, separators=(",", ":"))

        manifest = self.session.post(
            url=self.config["endpoints"]["vod"],
            data=body,
            headers=dict(**sky_headers, **{
                "Accept": "application/vnd.playvod.v1+json",
                "Content-Type": "application/vnd.playvod.v1+json",
                "X-Sky-Signature": self.create_signature_header(
                    method="POST",
                    path="/video/playouts/vod",
                    sky_headers=sky_headers,
                    body=body,
                    timestamp=int(time.time())
                )
            })
        ).json()
        if "errorCode" in manifest:
            raise self.log.exit(f" - An error occurred: {manifest['description']} [{manifest['errorCode']}]")

        self.license_api = manifest["protection"]["licenceAcquisitionUrl"]
        self.license_bt = manifest["protection"]["licenceToken"]

        tracks = Tracks.from_mpd(
            url=manifest["asset"]["endpoints"][0]["url"],
            session=self.session,
            source=self.ALIASES[0]
        )
        
        if supported_colour_spaces == ["HDR10"]:
            for track in tracks.videos:
                track.hdr10 = True if supported_colour_spaces == ["HDR10"] else False
        if supported_colour_spaces == ["DolbyVision"]:
            for track in tracks.videos:
                track.dolbyvison = True if supported_colour_spaces == ["DV"] else False

        for track in tracks:
            track.needs_proxy = False

        for track in tracks.audios:
            if track.language.territory == "AD":
                # This is supposed to be Audio Description, not Andorra
                track.language.territory = None

        return tracks

    def get_chapters(self, title):
        return []

    def license(self, challenge, **_):
        request = self.session.post(
            url=self.license_api,
            headers={
                "Accept": "*",
                "X-Sky-Signature": self.create_signature_header(
                    method="POST",
                    path="/" + self.license_api.split("://", 2)[1].split("/", 1)[1],
                    sky_headers={},
                    body="",
                    timestamp=int(time.time())
                )
            },
            data=challenge  # expects bytes
        )
        return request.text
    # Service specific functions

    def configure(self):
        self.session.headers.update({"Origin": "https://www.peacocktv.com"})
        self.log.info("Getting Peacock Client configuration")
        if self.config["client"]["platform"] != "PC":
            self.service_config = self.session.get(
                url=self.config["endpoints"]["config"].format(
                    territory=self.config["client"]["territory"],
                    provider=self.config["client"]["provider"],
                    proposition=self.config["client"]["proposition"],
                    device=self.config["client"]["platform"],
                    version=self.config["client"]["config_version"],
                )
            ).json()
        self.hmac_key = bytes(self.config["security"]["signature_hmac_key_v4"], "utf-8")
        self.log.info("Getting Authorization Tokens")
        self.tokens = self.get_tokens()
        self.log.info("Verifying Authorization Tokens")
        if not self.verify_tokens():
            raise self.log.exit(" - Failed! Cookies might be outdated.")

    @staticmethod
    def calculate_sky_header_md5(headers):
        if len(headers.items()) > 0:
            headers_str = "\n".join(f"{x[0].lower()}: {x[1]}" for x in headers.items()) + "\n"
        else:
            headers_str = "{}"
        return str(hashlib.md5(headers_str.encode()).hexdigest())

    @staticmethod
    def calculate_body_md5(body):
        return str(hashlib.md5(body.encode()).hexdigest())

    def calculate_signature(self, msg):
        digest = hmac.new(self.hmac_key, bytes(msg, "utf-8"), hashlib.sha1).digest()
        return str(base64.b64encode(digest), "utf-8")

    def create_signature_header(self, method, path, sky_headers, body, timestamp):
        data = "\n".join([
            method.upper(),
            path,
            "",  # important!
            self.config["client"]["client_sdk"],
            "1.0",
            self.calculate_sky_header_md5(sky_headers),
            str(timestamp),
            self.calculate_body_md5(body)
        ]) + "\n"

        signature_hmac = self.calculate_signature(data)

        return self.config["security"]["signature_format"].format(
            client=self.config["client"]["client_sdk"],
            signature=signature_hmac,
            timestamp=timestamp
        )

    def get_tokens(self):
        # Try to get cached tokens
        tokens_cache_path = self.get_cache("tokens_{profile}_{id}.json".format(
            profile=self.profile,
            id=self.config["client"]["id"]
        ))
        if os.path.isfile(tokens_cache_path):
            with open(tokens_cache_path, encoding="utf-8") as fd:
                tokens = json.load(fd)
            tokens_expiration = tokens.get("tokenExpiryTime", None)
            if tokens_expiration and datetime.strptime(tokens_expiration, "%Y-%m-%dT%H:%M:%S.%fZ") > datetime.now():
                return tokens

        # Get all SkyOTT headers
        sky_headers = {
            # Order of these matters!
            "X-SkyOTT-Agent": ".".join([
                self.config["client"]["proposition"],
                self.config["client"]["device"],
                self.config["client"]["platform"]
            ]).lower(),
            "X-SkyOTT-Device": self.config["client"]["device"],
            "X-SkyOTT-Platform": self.config["client"]["platform"],
            "X-SkyOTT-Proposition": self.config["client"]["proposition"],
            "X-SkyOTT-Provider": self.config["client"]["provider"],
            "X-SkyOTT-Territory": self.config["client"]["territory"]
        }
        
        print(self.session.cookies)

        try:
            # Call personas endpoint to get the accounts personaId
            personas = self.session.get(
                url=self.config["endpoints"]["personas"],
                headers=dict(**sky_headers, **{
                    "Accept": "application/vnd.persona.v1+json",
                    "Content-Type": "application/vnd.persona.v1+json",
                    "X-SkyOTT-TokenType": self.config["client"]["auth_scheme"]
                })
            ).json()
        except requests.HTTPError as e:
            error = e.response.json()
            if "message" in error and "code" in error:
                error = f"{error['message']} [{error['code']}]"
                if "bad credentials" in error.lower():
                    error += ". Cookies may be expired or invalid."
                raise self.log.exit(f" - Unable to get persona ID: {error}")
            raise self.log.exit(f" - HTTP Error {e.response.status_code}: {e.response.reason}")
        persona = personas["personas"][0]["personaId"]

        # Craft the body data that will be sent to the tokens endpoint, being minified and order matters!
        body = json.dumps({
            "auth": {
                "authScheme": self.config["client"]["auth_scheme"],
                "authIssuer": self.config["client"]["auth_issuer"],
                "provider": self.config["client"]["provider"],
                "providerTerritory": self.config["client"]["territory"],
                "proposition": self.config["client"]["proposition"],
                "personaId": persona
            },
            "device": {
                "type": self.config["client"]["device"],
                "platform": self.config["client"]["platform"],
                "id": self.config["client"]["id"],
                "drmDeviceId": self.config["client"]["drm_device_id"]
            }
        }, separators=(",", ":"))

        # Get the tokens
        tokens = self.session.post(
            url=self.config["endpoints"]["tokens"],
            headers=dict(**sky_headers, **{
                "Accept": "application/vnd.tokens.v1+json",
                "Content-Type": "application/vnd.tokens.v1+json",
                "X-Sky-Signature": self.create_signature_header(
                    method="POST",
                    path="/auth/tokens",
                    sky_headers=sky_headers,
                    body=body,
                    timestamp=int(time.time())
                )
            }),
            data=body
        ).json()

        os.makedirs(os.path.dirname(tokens_cache_path), exist_ok=True)
        with open(tokens_cache_path, "w", encoding="utf-8") as fd:
            json.dump(tokens, fd)

        return tokens

    def verify_tokens(self):
        """Verify the tokens by calling the /auth/users/me endpoint and seeing if it works"""
        sky_headers = {
            # order of these matter!
            "X-SkyOTT-Device": self.config["client"]["device"],
            "X-SkyOTT-Platform": self.config["client"]["platform"],
            "X-SkyOTT-Proposition": self.config["client"]["proposition"],
            "X-SkyOTT-Provider": self.config["client"]["provider"],
            "X-SkyOTT-Territory": self.config["client"]["territory"],
            "X-SkyOTT-UserToken": self.tokens["userToken"]
        }
        try:
            self.session.get(
                url=self.config["endpoints"]["me"],
                headers=dict(**sky_headers, **{
                    "Accept": "application/vnd.userinfo.v2+json",
                    "Content-Type": "application/vnd.userinfo.v2+json",
                    "X-Sky-Signature": self.create_signature_header(
                        method="GET",
                        path="/auth/users/me",
                        sky_headers=sky_headers,
                        body="",
                        timestamp=int(time.time())
                    )
                })
            )
        except requests.HTTPError:
            return False
        else:
            return True
