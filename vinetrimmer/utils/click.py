import importlib
import logging
import re

import click

from vinetrimmer import services
from vinetrimmer.services.BaseService import BaseService
from vinetrimmer.utils.collections import as_list


log = logging.getLogger("click")


class ContextData:
    def __init__(self, config, vaults, cdm, profile=None, cookies=None, credentials=None):
        self.config = config
        self.vaults = vaults
        self.cdm = cdm
        self.profile = profile
        self.cookies = cookies
        self.credentials = credentials


class AliasedGroup(click.Group):
    def get_command(self, ctx, cmd_name):
        rv = click.Group.get_command(self, ctx, cmd_name)
        if rv is not None:
            setattr(services, cmd_name, getattr(
                importlib.import_module(f"vinetrimmer.services.{cmd_name.lower()}"), cmd_name
            ))
            return rv

        for key, aliases in services.SERVICE_MAP.items():
            if cmd_name.lower() in map(str.lower, aliases):
                setattr(services, key, getattr(importlib.import_module(f"vinetrimmer.services.{key.lower()}"), key))
                return click.Group.get_command(self, ctx, key)

        service = services.get_service_key(cmd_name)

        if not service:
            title_id = None

            for x in dir(services):
                x = getattr(services, x)

                if isinstance(x, type) and issubclass(x, BaseService) and x != BaseService:
                    title_re = as_list(getattr(x, "TITLE_RE", []))
                    for regex in title_re:
                        m = re.search(regex, cmd_name)
                        if m and m.group().startswith(("http://", "https://", "urn:")):
                            title_id = m.group("id")
                            break

                if title_id:
                    ctx.params["service_name"] = x.__name__
                    setattr(services, x.__name__, getattr(
                        importlib.import_module(f"vinetrimmer.services.{x.__name__.lower()}"), x.__name__
                    ))
                    importlib.import_module(f"vinetrimmer.services.{x.__name__.lower()}")
                    ctx.params["title"] = cmd_name
                    return click.Group.get_command(self, ctx, x.__name__)

            if not title_id:
                raise log.exit(" - Unable to guess service from title ID")

    def list_commands(self, ctx):
        return sorted(self.commands, key=str.casefold)


def _choice(ctx, param, value, value_map):
    if value is None:
        return None

    if value.lower() in value_map:
        return value_map[value.lower()]
    else:
        valid_values = {x: None for x in value_map.values()}
        valid_values = ", ".join(repr(x) for x in valid_values)
        ctx.fail(f"Invalid value for {param.name!r}: {value!r} is not one of {valid_values}.")


def acodec_param(ctx, param, value):
    return _choice(ctx, param, value, {
        "aac": "AAC",
        "ac3": "AC3",
        "ac-3": "AC3",
        "dd": "AC3",
        "ec3": "EC3",
        "ec-3": "EC3",
        "eac3": "EC3",
        "e-ac3": "EC3",
        "e-ac-3": "EC3",
        "dd+": "EC3",
        "ddp": "EC3",
        "vorb": "VORB",
        "vorbis": "VORB",
        "opus": "OPUS",
    })


def language_param(ctx, param, value):
    if isinstance(value, list):
        return value
    if not value:
        return []
    return re.split(r"\s*[,;]\s*", value)


def quality_param(ctx, param, value):
    if not value:
        return None

    if value.lower() == "sd":
        return "SD"

    if value.lower() == "4k":
        return 2160

    try:
        return int(value.lower().rstrip("p"))
    except TypeError:
        ctx.fail(
            f"expected string for int() conversion, got {value!r} of type {value.__class__.__name__}",
            param,
            ctx
        )
    except ValueError:
        ctx.fail(f"{value!r} is not a valid integer", param, ctx)


def range_param(ctx, param, value):
    return _choice(ctx, param, value, {
        "sdr": "SDR",
        "hdr": "HDR10",
        "hdr10": "HDR10",
        "hlg": "HLG",
        "dv": "DV",
        "dovi": "DV",
    })


def vcodec_param(ctx, param, value):
    return _choice(ctx, param, value, {
        "h264": "H264",
        "avc": "H264",
        "h265": "H265",
        "hevc": "H265",
        "vp9": "VP9",
        "av1": "AV1",
    })


def wanted_param(ctx, param, value):
    MIN_EPISODE = 0
    MAX_EPISODE = 9999

    def parse_tokens(*tokens):
        """
        Parse multiple tokens or ranged tokens as '{s}x{e}' strings.

        Supports exclusioning by putting a `-` before the token.

        Example:
            >>> parse_tokens("S01E01")
            ["1x1"]
            >>> parse_tokens("S02E01", "S02E03-S02E05")
            ["2x1", "2x3", "2x4", "2x5"]
            >>> parse_tokens("S01-S05", "-S03", "-S02E01")
            ["1x0", "1x1", ..., "2x0", (...), "2x2", (...), "4x0", ..., "5x0", ...]
        """
        if len(tokens) == 0:
            return []
        computed = []
        exclusions = []
        for token in tokens:
            exclude = token.startswith("-")
            if exclude:
                token = token[1:]
            parsed = [
                re.match(r"^S(?P<season>\d+)(E(?P<episode>\d+))?$", x, re.IGNORECASE)
                for x in re.split(r"[:-]", token)
            ]
            if len(parsed) > 2:
                ctx.fail(f"Invalid token, only a left and right range is acceptable: {token}")
            if len(parsed) == 1:
                parsed.append(parsed[0])
            if any(x is None for x in parsed):
                ctx.fail(f"Invalid token, syntax error occurred: {token}")
            from_season, from_episode = [
                int(v) if v is not None else MIN_EPISODE
                for k, v in parsed[0].groupdict().items() if parsed[0]
            ]
            to_season, to_episode = [
                int(v) if v is not None else MAX_EPISODE
                for k, v in parsed[1].groupdict().items() if parsed[1]
            ]
            if from_season > to_season:
                ctx.fail(f"Invalid range, left side season cannot be bigger than right side season: {token}")
            if from_season == to_season and from_episode > to_episode:
                ctx.fail(f"Invalid range, left side episode cannot be bigger than right side episode: {token}")
            for s in range(from_season, to_season + 1):
                for e in range(
                    from_episode if s == from_season else 0,
                    (MAX_EPISODE if s < to_season else to_episode) + 1
                ):
                    (computed if not exclude else exclusions).append(f"{s}x{e}")
        for exclusion in exclusions:
            if exclusion in computed:
                computed.remove(exclusion)
        return list(set(computed))

    if value:
        return parse_tokens(*re.split(r"\s*[,;]\s*", value))
