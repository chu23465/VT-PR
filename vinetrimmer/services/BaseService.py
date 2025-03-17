import json
import logging
import os
import re
from abc import ABC

import requests
from requests.adapters import HTTPAdapter, Retry

from vinetrimmer.config import config, directories
from vinetrimmer.utils import try_get
from vinetrimmer.utils.collections import as_list
from vinetrimmer.utils.io import get_ip_info


class BaseService(ABC):
    """
    The service base class.
    This should not be directly used as a service file, instead make a new class deriving this one:

    ```
    from vinetrimmer.services.BaseService import BaseService

    ...

    class ServiceName(BaseService):

        ALIASES = ["DSNP", "disneyplus", "disney+"]  # first being the service tag (case-sensitive)
        GEOFENCE = ["us"]  # required region/country for this service. empty list == no specific region.

        def __init__(self, title, **kwargs):
            self.title = title

            # make sure the above 3 occur BEFORE the super().__init__() call below.
            super().__init__(**kwargs)  # re-route the Base related init args

            # service specific variables are recommended to be placed after the super().__init__() call

            # instead of flooding up __init__ with logic, initialize the variables as default values
            # here, and then call a new service specific (e.g. "configure()") in which has all the
            # preparation logic. This allows for cleaner looking service code.

        # from here, simply implement all the @abstractmethod functions seen in BaseClass.

        # e.g. def get_titles(...

        # After all the Abstract functions, I recommend putting any service specific functions
        # separated by a comment denoting that.

        # After those, I also recommend putting any service specific classes once again separated
        # by a comment denoting that.
    ```

    This class deals with initializing and preparing of all related code that's common among services.
    """

    # Abstract class variables
    ALIASES = []  # begin with source tag (case-sensitive) and name aliases (case-insensitive)
    GEOFENCE = []  # list of ip regions required to use the service. empty list == no specific region.

    def __init__(self, ctx):
        self.config = ctx.obj.config
        self.cookies = ctx.obj.cookies
        self.credentials = ctx.obj.credentials

        self.log = logging.getLogger(self.ALIASES[0])
        self.session = self.get_session()

        if ctx.parent.params["no_proxy"]:
            return

        proxy = ctx.parent.params["proxy"] or next(iter(self.GEOFENCE), None)
        if proxy:
            if len("".join(i for i in proxy if not i.isdigit())) == 2:  # e.g. ie, ie12, us1356
                proxy = self.get_proxy(proxy)
            if proxy:
                if "://" not in proxy:
                    # assume a https proxy port
                    proxy = f"https://{proxy}"
                self.session.proxies.update({"all": proxy})
            else:
                self.log.info(" + Proxy was skipped as current region matches")

    def get_session(self):
        """
        Creates a Python-requests Session, adds common headers
        from config, cookies, retry handler, and a proxy if available.
        :returns: Prepared Python-requests Session
        """
        session = requests.Session()
        session.mount("https://", HTTPAdapter(
            max_retries=Retry(
                total=5,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
            )
        ))
        session.hooks = {
            "response": lambda r, *_, **__: r.raise_for_status(),
        }
        session.headers.update(config.headers)
        session.cookies.update(self.cookies or {})
        return session

    # Abstract functions

    def get_titles(self):
        """
        Get Titles for the provided title ID.

        Return a Title object for every unique piece of content found by the Title ID.
        Each `Title` object should be thought of as one output file/download. E.g. a movie should be one Title,
        and each episode of a TV show would also be one Title, where as a Season would be multiple Title's, one
        per episode.

        Each Title object must contain `title_name` (the Show or Movie name).
        For TV, it also requires `season` and `episode` numbers, with `episode_name` being optional
            but ideally added as well.
        For Movies, it has no further requirements but `year` would ideally be added.

        You can return one Title object, or a List of Title objects.

        For any further data specific to each title that you may need in the later abstract methods,
        add that data to the `service_data` variable which can be of any type or value you wish.

        :return: One of or a List of Title objects.
        """
        raise NotImplementedError

    def get_tracks(self, title):
        """
        Get Track objects of the Title.

        Return a Tracks object, which itself can contain Video, Audio, Subtitle or even Chapters.
        Tracks.videos, Tracks.audios, Tracks.subtitles, and Track.chapters should be a List of Track objects.

        Each Track in the Tracks should represent a Video/Audio Stream/Representation/Adaptation or
        a Subtitle file.

        While one Track should only hold information for one stream/downloadable, try to get as many
        unique Track objects per stream type so Stream selection by the root code can give you more
        options in terms of Resolution, Bitrate, Codecs, Language, e.t.c.

        No decision making or filtering of which Tracks get returned should happen here. It can be
        considered an error to filter for e.g. resolution, codec, and such. All filtering based on
        arguments will be done by the root code automatically when needed.

        Make sure you correctly mark which Tracks are encrypted or not via its `encrypted` variable.

        If you are able to obtain the Track's KID (Key ID) as a 32 char (16 bit) HEX string, provide
        it to the Track's `kid` variable as it will speed up the decryption process later on. It may
        or may not be needed, that depends on the service. Generally if you can provide it, without
        downloading any of the Track's stream data, then do.

        :param title: The current `Title` from get_titles that is being executed.
        :return: Tracks object containing Video, Audio, Subtitles, and Chapters, if available.
        """
        raise NotImplementedError

    def get_chapters(self, title):
        """
        Get MenuTracks chapter objects of the Title.

        Return a list of MenuTracks objects. This will be run after get_tracks. If there's anything
        from the get_tracks that may be needed, e.g. "device_id" or a-like, store it in the class
        via `self` and re-use the value in get_chapters.

        How it's used is generally the same as get_titles. These are only separated as to reduce
        function complexity and keep them focused on simple tasks.

        You do not need to sort or order the chapters in any way. However, you do need to filter
        and alter them as needed by the service. No modification is made after get_chapters is
        ran. So that means ensure that the MenuTracks returned have consistent Chapter Titles
        and Chapter Numbers.

        :param title: The current `Title` from get_titles that is being executed.
        :return: List of MenuTrack objects, if available, empty list otherwise.
        """
        return []

    def certificate(self, challenge, title, track, session_id):
        """
        Get the Service Privacy Certificate.
        This is supplied to the Widevine CDM for privacy mode operations.

        If the certificate is a common certificate (one shared among various services),
        then return `None` and it will be used instead.

        Once you obtain the certificate, hardcode the certificate here and return it to reduce
        unnecessary HTTP requests.

        :param challenge: The service challenge, providing this to a License endpoint should return the
            privacy certificate that the service uses.
        :param title: The current `Title` from get_titles that is being executed. This is provided in
            case it has data needed to be used, e.g. for a HTTP request.
        :param track: The current `Track` needing decryption. Provided for same reason as `title`.
        :param session_id: This is the session ID bytes blob used for storing Widevine session data.
            It has no real meaning or syntax to its value, but some HTTP requests may ask for one.
        :return: The Service Privacy Certificate as Bytes or a Base64 string. Don't Base64 Encode or
            Decode the data, return as is to reduce unnecessary computations.
        """
        return self.license(challenge, title, track, session_id)

    def license(self, challenge, title, track, session_id):
        """
        Get the License response for the specified challenge and title data.
        This can be decrypted and read by the Widevine CDM to return various keys
        like Content Keys or HDCP test keys.

        This is a very important request to get correct. A bad, unexpected, or missing value
        in the request can cause your key to be detected and promptly banned, revoked,
        disabled, or downgraded.

        :param challenge: The license challenge from the Widevine CDM.
        :param title: The current `Title` from get_titles that is being executed. This is provided in
            case it has data needed to be used, e.g. for a HTTP request.
        :param track: The current `Track` needing decryption. Provided for same reason as `title`.
        :param session_id: This is the session ID bytes blob used for storing Widevine session data.
            It has no real meaning or syntax to its value, but some HTTP requests may ask for one.
        :return: The License response as Bytes or a Base64 string. Don't Base64 Encode or
            Decode the data, return as is to reduce unnecessary computations.
        """
        raise NotImplementedError

    # Convenience functions to be used by the inheritor

    def parse_title(self, ctx, title):
        title = title or ctx.parent.params.get("title")
        if not title:
            self.log.exit(" - No title ID specified")
        if not getattr(self, "TITLE_RE"):
            self.title = title
            return {}
        for regex in as_list(self.TITLE_RE):
            m = re.search(regex, title)
            if m:
                self.title = m.group("id")
                return m.groupdict()
        self.log.warning(f" - Unable to parse title ID {title!r}, using as-is")
        self.title = title

    def get_cache(self, key):
        """
        Get path object for an item from service Cache. The path object can then be
        used to read or write to the cache under the item's key.

        Parameters:
            key: A string similar to a relative path to an item.
        """
        return os.path.join(directories.cache, self.ALIASES[0], key)

    # Functions intended to be used here in BaseClass internally only

    def get_proxy(self, region):
        if not region:
            raise self.log.exit("Region cannot be empty")
        region = region.lower()

        self.log.info(f"Obtaining a proxy to \"{region}\"")

        if get_ip_info()["countryCode"].lower() == "".join(i for i in region if not i.isdigit()):
            return None  # no proxy necessary

        if config.proxies.get(region):
            proxy = config.proxies[region]
            self.log.info(f" + {proxy}")
        elif config.nordvpn.get("username") and config.nordvpn.get("password"):
            proxy = self.get_nordvpn_proxy(region)
            self.log.info(f" + {proxy} (via NordVPN)")
        else:
            raise self.log.exit(" - Unable to obtain a proxy")

        if "://" not in proxy:
            # assume a https proxy port
            proxy = f"https://{proxy}"

        return proxy

    def get_nordvpn_proxy(self, region):
        proxy = f"https://{config.nordvpn['username']}:{config.nordvpn['password']}@"
        if any(char.isdigit() for char in region):
            proxy += f"{region}.nordvpn.com"  # direct server id
        elif try_get(config.nordvpn, lambda x: x["servers"][region]):
            proxy += f"{region}{config.nordvpn['servers'][region]}.nordvpn.com"  # configured server id
        else:
            hostname = self.get_nordvpn_server(region)  # get current recommended server id
            if not hostname:
                raise self.log.exit(f" - NordVPN doesn't contain any servers for the country \"{region}\"")
            proxy += hostname
        return proxy + ":89"  # https: 89, http: 80

    def get_nordvpn_server(self, country):
        """
        Get the recommended NordVPN server hostname for a specified Country.
        :param country: Country (in alpha 2 format, e.g. 'US' for United States)
        :returns: Recommended NordVPN server hostname, e.g. `us123.nordvpn.com`
        """
        # Get the Country's NordVPN ID
        countries = self.session.get(
            url="https://nordvpn.com/wp-admin/admin-ajax.php",
            params={"action": "servers_countries"}
        ).json()
        country_id = [x["id"] for x in countries if x["code"].lower() == country.lower()]
        if not country_id:
            return None
        country_id = country_id[0]
        # Get the most recommended server for the country and return it
        recommendations = self.session.get(
            url="https://nordvpn.com/wp-admin/admin-ajax.php",
            params={
                "action": "servers_recommendations",
                "filters": json.dumps({"country_id": country_id})
            }
        ).json()
        return recommendations[0]["hostname"]
