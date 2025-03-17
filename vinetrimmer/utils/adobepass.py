import os
from abc import ABC

from yt_dlp import YoutubeDL
from yt_dlp.extractor.adobepass import AdobePassIE


class AdobePassVT(AdobePassIE, ABC):
    def __init__(self, credential, get_cache):
        super().__init__(
            YoutubeDL(
                {
                    "ap_mso": credential.extra,  # See yt_dlp.extractor.adobepass for supported MSO providers
                    "ap_username": credential.username,
                    "ap_password": credential.password,
                    "cachedir": os.path.realpath(get_cache("adobepass")),
                }
            )
        )
