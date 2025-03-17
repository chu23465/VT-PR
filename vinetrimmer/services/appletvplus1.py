import click

from base64 import b64encode, b64decode
from datetime import datetime, timedelta
from json import loads
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

    VIDEO_CODEC_MAP = {"H264": ["avc"], "H265": ["hvc", "hev", "dvh"]}

    AUDIO_CODEC_MAP = {"AAC": ["HE", "stereo"], "AC3": ["ac3"], "EC3": ["ec3", "atmos"]}

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

        self.extra_server_parameters: Optional[dict] = None

        self.configure()

    def get_titles(self) -> list[Title]:
        titles = list()

        req = None
        for i in range(2):
            try:
                req = self.session.get(
                    url=self.config["endpoints"]["title"].format(
                        types={0: "shows", 1: "movies"}[i], cid=self.title
                    ),
                    params={
                        "caller": "web",
                        "count": "100",
                        "ctx_brand": "tvs.sbd.4000",
                        "l": "en",
                        "locale": "en-US",
                        "mfr": "Apple",
                        "pfm": "appletv",
                        "sf": "143441",
                        "skip": "0",
                        "utsk": "6e3013c6d6fae3c2::::::235656c069bb0efb",
                        "v": "56",
                    },
                )

            except HTTPError as error:
                if error.response.status_code != 404:
                    raise

        title = req.json()

        if title["data"]["content"]["type"] == "Movie":
            titles.append(
                Title(
                    id_=self.title,
                    type_=Title.Types.MOVIE,
                    name=title["data"]["content"]["title"],
                    year=(
                        datetime(1970, 1, 1)
                        + timedelta(
                            milliseconds=title["data"]["content"]["releaseDate"]
                        )
                    ).year,
                    original_lang=title["data"]["content"]["originalSpokenLanguages"][
                        0
                    ]["locale"],
                    source=self.ALIASES[0],
                    service_data=title["data"]["content"],
                )
            )

        else:
            req = self.session.get(
                url=self.config["endpoints"]["episode"].format(cid=self.title),
                params={
                    "caller": "web",
                    "count": "100",
                    "ctx_brand": "tvs.sbd.4000",
                    "l": "en",
                    "locale": "en-US",
                    "mfr": "Apple",
                    "pfm": "appletv",
                    "sf": "143441",
                    "skip": "0",
                    "utsk": "6e3013c6d6fae3c2::::::235656c069bb0efb",
                    "v": "56",
                },
            )

            data = req.json()

            for episode in data["data"]["episodes"]:
                titles.append(
                    Title(
                        id_=self.title,
                        type_=Title.Types.TV,
                        name=episode["showTitle"],
                        year=(
                            datetime(1970, 1, 1)
                            + timedelta(
                                milliseconds=title["data"]["content"]["releaseDate"]
                            )
                        ).year,
                        season=episode["seasonNumber"],
                        episode=episode["episodeNumber"],
                        episode_name=episode.get("title"),
                        original_lang=title["data"]["content"][
                            "originalSpokenLanguages"
                        ][0]["locale"],
                        source=self.ALIASES[0],
                        service_data=episode,
                    )
                )

        return titles

    def get_tracks(self, title: Title) -> Tracks:
        tracks = Tracks()

        req = self.session.get(
            url=self.config["endpoints"]["manifest.xml"].format(
                cid=title.service_data["id"]
            ),
            params={
                "caller": "web",
                "count": "100",
                "ctx_brand": "tvs.sbd.4000",
                "l": "en",
                "locale": "en-US",
                "mfr": "Apple",
                "pfm": "appletv",
                "sf": "143441",
                "skip": "0",
                "utsk": "6e3013c6d6fae3c2::::::235656c069bb0efb",
                "v": "56",
            },
        )

        data = req.json()

        stream_data = data["data"]["content"]["playables"][0]

        if not stream_data["isEntitledToPlay"]:
            raise self.log.exit(" - User is not entitled to play this title")

        self.extra_server_parameters = stream_data["assets"][
            "fpsKeyServerQueryParameters"
        ]

        req = get(
            url=stream_data["assets"]["hlsUrl"],
            headers={"User-Agent": "AppleTV6,2/11.1"},
        )

        tracks.add(
            Tracks.from_m3u8(
                master=m3u8loads(content=req.text, uri=req.url), source=self.ALIASES[0]
            )
        )

        for track in tracks:
            track.extra = {"url": track.url, "manifest.xml": track.extra}
            if isinstance(track, VideoTrack):
                track.encrypted = True
                track.needs_ccextractor_first = True

            elif isinstance(track, AudioTrack):
                track.encrypted = True

            elif isinstance(track, TextTrack):
                track.codec = "vtt"

        quality = None
        for line in req.text.splitlines():
            if line.startswith("#--"):
                quality = {"SD": 480, "HD720": 720, "HD": 1080, "UHD": 2160}.get(
                    line.split()[2]
                )

            elif not line.startswith("#"):
                track = next(
                    (x for x in tracks.videos if x.extra["manifest.xml"].uri == line), None
                )
                if track:
                    track.extra["quality"] = quality

        for track in tracks:
            track_data = track.extra["manifest.xml"]
            if isinstance(track, AudioTrack):
                bitrate = search(
                    pattern=r"&g=(\d+?)&",
                    string=track_data.uri,
                )
                if bitrate:
                    track.bitrate = int(bitrate[1][-3::]) * 1000

                else:
                    raise ValueError(
                        f"Unable to get a bitrate value for Track {track.id}"
                    )

                track.codec = track.codec.replace("_vod", "")

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

        return tracks

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
                                "challenge": b64encode(
                                    challenge.encode("UTF-8")
                                ).decode("UTF-8"),
                                "key-system": "com.microsoft.playready",
                                "uri": f"data:text/plain;charset=UTF-16;base64,{track.pssh_playready}",
                                "id": 1,
                                "lease-action": "start",
                                "adamId": self.extra_server_parameters["adamId"],
                                "isExternal": True,
                                "svcId": "tvs.vds.4078",
                            },
                        ],
                    },
                },
            )

        except HTTPError as error:
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

        req = self.session.get("https://tv.apple.com")
        data = req.text

        data = search(
            pattern=r'web-tv-app/config/environment"[\s\S]*?content="([^"]+)',
            string=data,
        )

        if data:
            data = loads(unquote(data[1]))

        else:
            raise ValueError(
                "Failed to get AppleTV+ WEB TV App Environment Configuration..."
            )

        self.session.headers.update(
            {
                "Authorization": f"Bearer {data['MEDIA_API']['token']}",
                "Media-User-Token": self.session.cookies.get_dict()["media-user-token"],
                "User-Agent": self.config["user_agent"],
                "X-Apple-Music-User-Token": self.session.cookies.get_dict()[
                    "media-user-token"
                ],
            }
        )
