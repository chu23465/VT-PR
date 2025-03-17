import logging
import re
import unicodedata
from enum import Enum

from langcodes import Language
from unidecode import unidecode

from vinetrimmer.objects.tracks import Tracks

VIDEO_CODEC_MAP = {
    "AVC": "H.264",
    "HEVC": "H.265"
}
DYNAMIC_RANGE_MAP = {
    "HDR10": "HDR",
    "HDR10+": "HDR",
    "HDR10 / HDR10+": "HDR",
    "Dolby Vision": "DV"
}
AUDIO_CODEC_MAP = {
    "E-AC-3": "DDP",
    "AC-3": "DD"
}


class Title:
    def __init__(self, id_, type_, name=None, year=None, season=None, episode=None, episode_name=None,
                 original_lang=None, source=None, service_data=None, tracks=None, filename=None):
        self.id = id_
        self.type = type_
        self.name = name
        self.year = int(year or 0)
        self.season = int(season or 0)
        self.episode = int(episode or 0)
        self.episode_name = episode_name
        self.original_lang = Language.get(original_lang) if original_lang else None
        self.source = source
        self.service_data = service_data or {}
        self.tracks = tracks or Tracks()
        self.filename = filename

        if not self.filename:
            # auto generated initial filename
            self.filename = self.parse_filename()

    def parse_filename(self, media_info=None, folder=False):
        from vinetrimmer.config import config

        if media_info:
            video_track = next(iter(media_info.video_tracks), None)
            if config.output_template.get("use_last_audio", False):
                audio_track = next(iter(reversed(media_info.audio_tracks)), None)
            else:
                audio_track = next(iter(media_info.audio_tracks), None)
        else:
            video_track = None
            audio_track = None

        # create the initial filename string

        if video_track:
            quality = video_track.height
            aspect = [int(float(x)) for x in video_track.other_display_aspect_ratio[0].split(":")]
            if len(aspect) == 1:
                aspect.append(1)
            aspect_w, aspect_h = aspect
            if aspect_w / aspect_h not in (16 / 9, 4 / 3):
                # We want the resolution represented in a 4:3 or 16:9 canvas
                # if it's not 4:3 or 16:9, calculate as if it's inside a 16:9 canvas
                # otherwise the track's height value is fine
                # We are assuming this title is some weird aspect ratio so most
                # likely a movie or HD source, so it's most likely widescreen so
                # 16:9 canvas makes the most sense
                quality = int(video_track.width * (9 / 16))
            if video_track.width == 1248:  # AMZN weird resolution (1248x520)
                quality = 720
            if isinstance(self.tracks.videos[0].extra, dict) and self.tracks.videos[0].extra.get("quality"):
                quality = self.tracks.videos[0].extra["quality"]
        else:
            quality = ""

        if audio_track:
            audio = f"{AUDIO_CODEC_MAP.get(audio_track.format) or audio_track.format}"
            audio += f"{float(sum({'LFE': 0.1}.get(x, 1) for x in audio_track.channel_layout.split(' '))):.1f} "
            if audio_track.format_additionalfeatures and "JOC" in audio_track.format_additionalfeatures:
                audio += "Atmos "
        else:
            audio = ""

        video = ""
        if video_track:
            if (video_track.hdr_format or "").startswith("Dolby Vision"):
                video += "DV "
            elif video_track.hdr_format_commercial:
                video += f"{DYNAMIC_RANGE_MAP.get(video_track.hdr_format_commercial)} "
            elif ("HLG" in (video_track.transfer_characteristics or "")
                  or "HLG" in (video_track.transfer_characteristics_original or "")):
                video += "HLG "
            if float(video_track.frame_rate) > 30 and self.source != "iP":
                video += "HFR "
            video += f"{VIDEO_CODEC_MAP.get(video_track.format) or video_track.format}"

        tag = config.tag
        if quality and quality <= 576:
            tag = config.tag_sd or tag

        if self.type == Title.Types.MOVIE:
            filename = config.output_template["movies"].format(
                title=self.name,
                year=self.year or "",
                quality=f"{quality}p" if quality else "",
                source=self.source,
                audio=audio,
                video=video,
                tag=tag,
            )
        else:
            episode_name = self.episode_name
            # TODO: Maybe we should only strip these if all episodes have such names.
            if re.fullmatch(r"(?:Episode|Chapter|Capitulo|Folge) \d+", episode_name or ""):
                episode_name = None

            filename = config.output_template["series"].format(
                title=self.name,
                season_episode=(f"S{self.season:02}"
                                + (f"E{self.episode:02}" if (self.episode is not None and not folder) else "")),
                episode_name=(episode_name or "") if not folder else "",
                quality=f"{quality}p" if quality else "",
                source=self.source,
                audio=audio,
                video=video,
                tag=tag,
            )

        filename = re.sub(r"\s+", ".", filename)
        filename = re.sub(r"\.\.+", ".", filename)
        filename = re.sub(fr"\.+(-{re.escape(config.tag)})$", r"\1", filename)
        filename = filename.rstrip().rstrip(".")  # remove whitespace and last right-sided . if needed

        return self.normalize_filename(filename)

    @staticmethod
    def normalize_filename(filename):
        # replace all non-ASCII characters with ASCII equivalents
        filename = filename.replace("æ", "ae")
        filename = filename.replace("ø", "oe")
        filename = filename.replace("å", "aa")
        filename = filename.replace("'", "")
        filename = unidecode(filename)
        filename = "".join(c for c in filename if unicodedata.category(c) != "Mn")

        # remove or replace further characters as needed
        filename = filename.replace("/", " - ")  # e.g. amazon multi-episode titles
        filename = filename.replace("&", " and ")
        filename = filename.replace("$", "S")
        filename = re.sub(r"[:; ]", ".", filename)  # structural chars to .
        filename = re.sub(r"[\\*!?¿,'\"()<>|#]", "", filename)  # unwanted chars
        filename = re.sub(r"[. ]{2,}", ".", filename)  # replace 2+ neighbour dots and spaces with .
        return filename

    def is_wanted(self, wanted):
        if self.type != Title.Types.TV or not wanted:
            return True
        return f"{self.season}x{self.episode}" in wanted

    class Types(Enum):
        MOVIE = 1
        TV = 2


class Titles(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title_name = None

        if self:
            self.title_name = self[0].name

    def print(self):
        log = logging.getLogger("Titles")
        log.info(f"Title: {self.title_name}")
        if any(x.type == Title.Types.TV for x in self):
            log.info(f"Total Episodes: {len(self)}")
            log.info(
                "By Season: {}".format(
                    ", ".join(list(dict.fromkeys(
                        f"{x.season} ({len([y for y in self if y.season == x.season])})"
                        for x in self if x.type == Title.Types.TV
                    )))
                )
            )

    def order(self):
        """This will order the Titles to be oldest first."""
        self.sort(key=lambda t: int(t.year or 0))
        self.sort(key=lambda t: int(t.episode or 0))
        self.sort(key=lambda t: int(t.season or 0))

    def with_wanted(self, wanted):
        """Yield only wanted tracks."""
        for title in self:
            if title.is_wanted(wanted):
                yield title
