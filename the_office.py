import subprocess
import os

temp            = r"E:\Downloads\WV_rippers\tools\temp"
output          = r"E:\Downloads\CanalPlus"
mp4decrypt      = r"E:\Downloads\WV_rippers\tools\mp4decrypt.exe"
mkvpropedit     = r"E:\Programy\MKVToolNix\mkvpropedit.exe"
Nm3u8DLRE     = r"E:\Downloads\WV_rippers\tools\N_m3u8DL-RE.exe"
video_quality   = "best"
audio_lang      = "pol"
subs_lang       = "pol"
name            = "The.Office.PL.EPISODE.1080p.ANALplus.WEB-DL.AAC2.0.h264-TRad"


def download_and_decrypt(mpd, deckey, episode):
    name_fix = name.replace('EPISODE', episode)
    subprocess.call([Nm3u8DLRE, mpd, '--save-dir', output, '--save-name', name_fix, '--tmp-dir', temp, '--key', deckey, '-sv', video_quality, '-sa', 'lang='+audio_lang, '-ss', 'lang='+subs_lang, '-M', 'format=mkv', '--decryption-binary-path', mp4decrypt])

download_and_decrypt("https://r.cdn-ncplus.pl/vod/store01/BEL_70005415/_/hd4-hssdrm02.ism/manifest", "1c71615473c849aabf4ff6ce6cc613ca:7eeab8416988c2e5eee2a6ad1b92426c", "S03E00")

# download_and_decrypt("", "", "S01E0")