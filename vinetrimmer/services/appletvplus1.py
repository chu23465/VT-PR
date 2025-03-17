import click

from base64 import b64encode, b64decode
from datetime import datetime, timedelta
from json import loads, JSONDecodeError
from m3u8 import loads as m3u8loads
from re import search
from requests import get, HTTPError
from typing import Any, Optional, Union
from urllib.parse import unquote

from vinetrimmer.objects import Title, Tracks, VideoTrack, AudioTrack, TextTrack, MenuTrack  # fmt: skip
from vinetrimmer.services.BaseService import BaseService



class AppleTVPlus(BaseService):
    """
    Service code for Apple's TV Plus streaming service (https://tv.apple.com).

    \b
    WIP: decrypt and removal of bumper/dub cards

    \b
    Authorization: Cookies
    Security:
        Playready:
            SL150: Untested
            SL2000: 1080p
            SL3000: 2160p

        Widevine:
            L1: 2160p
            L2: Untested
            L3 (Chrome): 540p
            L3 (Android): 540p
    """

    ALIASES = ["ATVP", "appletvplus", "appletv+"]

    TITLE_RE = r"^(?:https?://tv\.apple\.com(?:/[a-z]{2})?/(?:movie|show|episode)/[a-z0-9-]+/)?(?P<id>umc\.cmc\.[a-z0-9]+)"  # noqa: E501


    VIDEO_CODEC_MAP = {
        "H264": ["avc"],
        "H265": ["hvc", "hev", "dvh"]
    }
    AUDIO_CODEC_MAP = {
        "AAC": ["HE", "stereo"],
        "AC3": ["ac3"],
        "EC3": ["ec3", "atmos"]
    }

    @staticmethod
    @click.command(name="AppleTVPlus", short_help="https://tv.apple.com")
    @click.argument("title", type=str, required=False)
    @click.pass_context
    def cli(ctx, **kwargs):
        return AppleTVPlus(ctx, **kwargs)

    def __init__(self, ctx, title: str) -> None:
        super().__init__(ctx=ctx)
        self.parse_title(ctx=ctx, title=title)

        self.acodec = ctx.parent.params["acodec"]
        self.alang = ctx.parent.params["alang"]
        self.subs_only = ctx.parent.params["subs_only"]
        self.vcodec = ctx.parent.params["vcodec"]
        self.range = ctx.parent.params["range_"] or "SDR"
        self.quality = ctx.parent.params["quality"] or 1080

        self.extra_server_parameters: Optional[dict] = None

        if ("HDR" in self.range) or ("DV" in self.range) or ((self.quality > 1080) if self.quality else False):
            self.log.info(" - Setting Video codec to H265 to get UHD")
            self.vcodec = "H265"

        self.configure()

    def get_titles(self) -> list[Title]:
        titles = list()

        req = None
        for i in range(2):
            try:
                req = self.session.get(
                    url=self.config["endpoints"]["title"].format(type={0: "shows", 1: "movies"}[i], id=self.title),
                    params=self.config["device"]
                )

            except HTTPError as error:
                if error.response.status_code != 404:
                    raise
            else:
                if req.ok:
                    break

        if not req:
            raise self.log.exit(f" - Title ID {self.title!r} could not be found.")
        try:
            title = req.json()["data"]["content"]
        except json.JSONDecodeError:
            raise ValueError(f"Failed to load title manifest: {r.text}")

        self.log.debug(title)

        if title["type"] == "Movie":
            titles.append(
                Title(
                    id_=self.title,
                    type_=Title.Types.MOVIE,
                    name=title["title"],
                    year=datetime.utcfromtimestamp(title["releaseDate"] / 1000).year,
                    original_lang=title["originalSpokenLanguages"][0]["locale"] if "originalSpokenLanguages" in title.keys() else "und",
                    source=self.ALIASES[0],
                    service_data=title,
                )
            )

        else:
            req = self.session.get(
                url=self.config["endpoints"]["tv_episodes"].format(id=self.title),
                params=self.config["device"]
            )

            try:
                episodes = req.json()["data"]["episodes"]
            except JSONDecodeError:
                raise ValueError(f"Failed to load episodes list: {req.text}")

            for episode in episodes:
                titles.append(
                    Title(
                        id_=self.title,
                        type_=Title.Types.TV,
                        name=episode["showTitle"],
                        year=datetime.utcfromtimestamp(title["releaseDate"] / 1000).year,
                        season=episode["seasonNumber"],
                        episode=episode["episodeNumber"],
                        episode_name=episode.get("title"),
                        original_lang=title["originalSpokenLanguages"][0]["locale"] if "originalSpokenLanguages" in title.keys() else "und",
                        source=self.ALIASES[0],
                        service_data=episode,
                    )
                )

        return titles

    def get_tracks(self, title: Title) -> Tracks:
        tracks = Tracks()

        req = self.session.get(
            url=self.config["endpoints"]["manifest"].format(id=title.service_data["id"]),
            params=self.config["device"]
        )

        
        try:
            data = req.json()
        except JSONDecodeError:
            raise ValueError(f"Failed to load stream data: {req.text}")

        stream_data = data["data"]["content"]["playables"][0]

        if not stream_data["isEntitledToPlay"]:
            self.log.debug(stream_data)
            raise self.log.exit(" - User is not entitled to play this title")

        self.extra_server_parameters = stream_data["assets"]["fpsKeyServerQueryParameters"]

        self.log.debug(self.extra_server_parameters)
        self.log.debug(stream_data["assets"]["hlsUrl"])

        req = get(
            url=stream_data["assets"]["hlsUrl"],
            headers={"User-Agent": "AppleTV6,2/11.1"}, # 'ATVE/1.1 FireOS/6.2.6.8 build/4A93 maker/Amazon model/FireTVStick4K FW/NS6268/2315'
        )

        tracks.add(
            Tracks.from_m3u8(
                master=m3u8loads(content=req.text, uri=req.url), source=self.ALIASES[0]
            )
        )


        for track in tracks:
            track.extra = {"url": track.url, "manifest.xml": track.extra}
            track_data = track.extra["manifest.xml"]
            if isinstance(track, VideoTrack):
                track.encrypted = True
                track.needs_ccextractor_first = True
                track.needs_proxy = False

            elif isinstance(track, AudioTrack):
                track.encrypted = True
                track.needs_proxy = False
                bitrate = search(pattern=r"&g=(\d+?)&", string=track_data.uri )
                if not bitrate:
                    bitrate = re.search(r"_gr(\d+)_", track_data.uri) # new
                if bitrate:
                    track.bitrate = int(bitrate[1][-3::]) * 1000

                else:
                    raise ValueError(f"Unable to get a bitrate value for Track {track.id}")

                track.codec = track.codec.replace("_vod", "")

            elif isinstance(track, TextTrack):
                track.codec = "vtt"

        quality = None
        for line in req.text.splitlines():
            if line.startswith("#--"):
                quality = {"SD": 480, "HD720": 720, "HD": 1080, "UHD": 2160}.get(line.split()[2])

            elif not line.startswith("#"):
                track = next(
                    (x for x in tracks.videos if x.extra["manifest.xml"].uri == line), None
                )
                if track:
                    track.extra["quality"] = quality

        tracks.videos = [
            x
            for x in tracks.videos
            if (x.codec or "")[:3] in self.VIDEO_CODEC_MAP[self.vcodec]
        ]

        if self.acodec:
            tracks.audios = [
                x
                for x in tracks.audios
                if (x.codec or "").split("-")[0] in self.AUDIO_CODEC_MAP[self.acodec]
            ]

        tracks.subtitles = [
            x
            for x in tracks.subtitles
            if (
                x.language in self.alang
                or (x.is_original_lang and "orig" in self.alang)
                or "all" in self.alang
            )
            or self.subs_only
            or not x.sdh
        ]

        try:
            return Tracks([
                # multiple CDNs, only want one
                x for x in tracks
                if any(
                    cdn in as_list(x.url)[0].split("?")[1].split("&") for cdn in ["cdn=ak", "cdn=vod-ak-aoc.tv.apple.com"]
                )
            ])
        except:
            return Tracks([x for x in tracks])

    def get_chapters(self, title: Title) -> list[MenuTrack]:
        chapters = list()

        return chapters

    def certificate(self, **_: Any) -> Optional[Union[str, bytes]]:
        return None

    def license(self, challenge: bytes, track: Tracks, **_):
        try:
            req = self.session.post(
                url=self.config["endpoints"]["license"],
                json={
                    "streaming-request": {
                        "version": 1,
                        "streaming-keys": [
                            {
                                "challenge": b64encode(challenge.encode("UTF-8")).decode("UTF-8"),
                                "key-system": "com.microsoft.playready",
                                "uri": f"data:text/plain;charset=UTF-16;base64,{track.pssh}",
                                "id": 1,
                                "lease-action": "start",
                                "adamId": self.extra_server_parameters["adamId"],
                                "isExternal": True,
                                "svcId": self.extra_server_parameters["svcId"],
                            },
                        ],
                    },
                },
                params=self.config["device"]
            )

        except HTTPError as error:
            self.log.warn(e)
            if not error.response.text:
                raise self.log.exit(" - No License Returned!")

            error = {
                -1001: "Invalid PSSH!",
                -1002: "Title not Owned!",
                -1021: "Insufficient Security!",
            }.get(error.response.json()["errorCode"])

            raise self.log.exit(
                f" - Failed to Get License! -> Error Code : {error.response.json()['errorCode']}"
            )

        data = req.json()

        if data["streaming-response"]["streaming-keys"][0]["status"] != 0:
            status = data["streaming-response"]["streaming-keys"][0]["status"]
            error = {
                -1001: "Invalid PSSH!",
                -1002: "Title not Owned!",
                -1021: "Insufficient Security!",
            }.get(status)

            raise self.log.exit(f" - Failed to Get License! -> {error} ({status})")

        return b64decode(
            data["streaming-response"]["streaming-keys"][0]["license"]
        ).decode()

    def configure(self) -> None:
        self.log.info(" + Logging into Apple TV+...")
        environment = self.get_environment_config()
        if not environment:
            raise ValueError("Failed to get AppleTV+ WEB TV App Environment Configuration...")
        self.session.headers.update({
            "User-Agent": self.config["user_agent"],
            "Authorization": f"Bearer {environment['MEDIA_API']['token']}",
            "media-user-token": self.session.cookies.get_dict()["media-user-token"],
            "x-apple-music-user-token": self.session.cookies.get_dict()["media-user-token"]
        })

    def get_environment_config(self):
        """Loads environment config data from WEB App's <meta> tag."""
        res = self.session.get("https://tv.apple.com").text
        env = search(pattern = r'web-tv-app/config/environment"[\s\S]*?content="([^"]+)', string = res)
        if not env:
            raise ValueError(
                "Failed to get AppleTV+ WEB TV App Environment Configuration..."
            )
        return loads(unquote(env[1]))

    def scan(self, start: int, length: int) -> list:

        # poetry run vt dl -al en -sl en --selected --proxy http://192.168.0.99:9766 --keys -q 2160 -v H265 ATVP 
        # poetry run vt dl -al en -sl en --selected --proxy http://192.168.0.99:9766 --keys -q 2160 -v H265 -r DV ATVP 

        urls = []
        params = self.config["device"]
        params["utscf"] = "OjAAAAEAAAAAAAAAEAAAACMA"
        params["nextToken"] = str(start)

        r = None
        try:
            r = self.session.get(
                url=self.config["endpoints"]["homecanvas"],
                params=params
            )
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                raise

        if not r:
            raise self.log.exit(f" -  Canvas endpoint errored out")
        try:
            shelves = r.json()["data"]["canvas"]["shelves"]
        except json.JSONDecodeError:
            raise ValueError(f"Failed to load title manifest: {r.text}")

        # TODO - Add check userisentitledtoplay before appending url
        for shelf in shelves:
            items = shelf["items"]
            for item in items:
                urls.append(item["url"])

        url_regex = re.compile(r"^(?:https?://tv\.apple\.com(?:/[a-z]{2})?/(?P<type>movie|show|episode)/[a-z0-9-]+/)?(?P<id>umc\.cmc\.[a-z0-9]+)")

        for url in urls:
            match = url_regex.match(url)

            if match:
                # Extract the title type and ID
                title_type = match.group("type") + "s"  # None if not present
                title_id = match.group("id")

            else:
                continue

            r = None
            try:
                r = self.session.get(
                    url=self.config["endpoints"]["title"].format(type=title_type, id=title_id),
                    params=self.config["device"]
                )
            except requests.HTTPError as e:
                if e.response.status_code != 404:
                    raise
            if not r:
                raise self.log.exit(f" - Title ID {self.title!r} could not be found.")
            try:
                shelves = r.json()["data"]["canvas"]["shelves"]
            except json.JSONDecodeError:
                raise ValueError(f"Failed to load title manifest: {r.text}")

            for shelf in shelves:
                if "uts.col.ContentRelated" in shelf["id"]:
                    items = shelf["items"]
                    for item in items:
                        if item["url"] not in urls:
                            # TODO - Add check userisentitledtoplay before appending url
                            urls.append(item["url"])

            if len(urls) >= length:
                break

        return urls