import os
import tempfile
from types import SimpleNamespace
from pathlib import Path

import yaml
from appdirs import AppDirs
from requests.utils import CaseInsensitiveDict

from vinetrimmer.objects.vaults import Vault
from vinetrimmer.utils.collections import merge_dict


class Config:
    @staticmethod
    def load_vault(vault):
        return Vault(**{
            "type_" if k == "type" else k: v for k, v in vault.items()
        })


class Directories:
    def __init__(self):
        self.app_dirs = AppDirs("vinetrimmer", False)
        self.package_root = Path(__file__).resolve().parent.parent
        self.configuration = self.package_root / "config"
        self.user_configs = self.package_root
        self.service_configs = self.user_configs / "Services"
        self.data = self.package_root
        self.downloads = Path(__file__).resolve().parents[2] / "Downloads"
        self.temp = Path(__file__).resolve().parents[2] / "Temp"
        self.cache = self.package_root / "Cache"
        self.cookies = self.data / "Cookies"
        self.logs = self.package_root / "Logs"
        self.devices = self.data / "devices"

class Filenames:
    def __init__(self):
        self.log = os.path.join(directories.logs, "vinetrimmer_{time}.log")
        self.root_config = os.path.join(directories.configuration, "vinetrimmer.yml")
        self.user_root_config = os.path.join(directories.user_configs, "vinetrimmer.yml")
        self.service_config = os.path.join(directories.configuration, "services", "{service}.yml")
        self.user_service_config = os.path.join(directories.service_configs, "{service}.yml")
        self.subtitles = os.path.join(directories.temp, "TextTrack_{id}_{language_code}.srt")
        self.chapters = os.path.join(directories.temp, "{filename}_chapters.txt")


directories = Directories()
filenames = Filenames()
with open(filenames.root_config) as fd:
    config = yaml.safe_load(fd)
with open(filenames.user_root_config) as fd:
    user_config = yaml.safe_load(fd)
merge_dict(config, user_config)
config = SimpleNamespace(**config)
credentials = config.credentials

# This serves two purposes:
# - Allow `range` to be used in the arguments section in the config rather than just `range_`
# - Allow sections like [arguments.Amazon] to work even if an alias (e.g. AMZN or amzn) is used.
#   CaseInsensitiveDict is used for `arguments` above to achieve case insensitivity.
# NOTE: The import cannot be moved to the top of the file, it will cause a circular import error.
from vinetrimmer.services import SERVICE_MAP  # noqa: E402

if "range_" not in config.arguments:
    config.arguments["range_"] = config.arguments.get("range_")
for service, aliases in SERVICE_MAP.items():
    for alias in aliases:
        config.arguments[alias] = config.arguments.get(service)
config.arguments = CaseInsensitiveDict(config.arguments)


