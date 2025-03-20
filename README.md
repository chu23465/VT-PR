# VineTrimmer-PlayReady
A tool to download and remove DRM from streaming services. A version of an old fork of [devine](https://github.com/devine-dl/devine).
Modified to remove Playready DRM instead of Widevine.

## Features
 - Progress Bars for decryption ([mp4decrypt](https://github.com/chu23465/bentoOldFork), Shaka)
 - Refresh Token fixed for Amazon service
 - Reprovision .prd after 2 days
 - ISM manifest support (Microsoft Smooth Streaming) (WIP/Experimental)
 - N_m3u8DL-RE downloader support

## Broken
 - `--bitrate CVBR+CBR` is currently broken
 - Atmos audio with ISM manifest (Amazon) is currently broken (Needs a working init.mp4). If the title has the atmos audio in MPD then it should work. 
 - ATVP service is currently broken in dev branch
 - Netflix service is currently broken (will probably be fixed Soon™)

If anyone has any idea how to fix above issues, feel free to open a pull request.

## Usage

1. Make sure git is installed in your system by running `git --version`. If not refer to [link](https://git-scm.com/book/en/v2/Getting-Started-Installing-Git)

2. Choose a branch, either `dev` or `main`. Use below command to download. (Recommended instead of downloading zip)
   ```bash
   git clone -b <branch-name> --single-branch https://github.com/chu23465/VT-PR
   ```
   
3. Navigate and find `install.bat`

4. Run `install.bat`
   
5. Activate venv using `venv.cmd`.

6. Run desired command using poetry.


## Updating

1. Backup your `vinetrimmer/Cookies/`, `vinetrimmer/Cache/`, `/Downloads` directories just in case.
   
2. Open a command prompt and navigate your `VT-PR` directory.
   
3. Recall the branch you downloaded and modify below command accordingly:
   ```bash
   git pull origin <branch-name>
   ```


### Config

`vinetrimmer.yml` located within the `/vinetrimmer/` folder.

`decryptor:` either `mp4decrypt` or `packager`

(shaka-packager fails to decrypt files downloaded from MSS manifests)

`tag:` tag for your release group

CDM can be configured per service or per profile.

```
cdm:
    default: {text}
    Amazon: {text}
```

All other option can be left to defaults, unless you know what you are doing. 

### General Options

Usage: vt.cmd [OPTIONS] COMMAND [ARGS]...

Options:
| Command line argument      | Description                                                                                   | Default Value                     |
|----------------------------|-----------------------------------------------------------------------------------------------|-----------------------------------|
|  -d, --debug               | Flag to enable debug logging                                                                  |  False                            |
|  -p, --profile             | Profile to use when multiple profiles are defined for a service.                              |  "default"                        |
|  -q, --quality             | Download Resolution                                                                           |  1080                             |
|  -v, --vcodec              | Video Codec                                                                                   |  H264                             |
|  -a, --acodec              | Audio Codec                                                                                   |  None                             |
|  -vb, --vbitrate           | Video Bitrate                                                                                 |  Max                              |
|  -ab, --abitrate           | Audio Bitrate                                                                                 |  Max                              |
|  -aa, --atmos              | Prefer Atmos Audio                                                                            |  False                            |
|  -r, --range               | Video Color Range `HDR`, `HDR10`, `DV`, `SDR`                                                 |  SDR                              |
|  -w, --wanted              | Wanted episodes, e.g. `S01-S05,S07`, `S01E01-S02E03`, `S02-S02E03`                            |  Default to all                   |
|  -al, --alang              | Language wanted for audio.                                                                    |  Defaults to original language    |
|  -sl, --slang              | Language wanted for subtitles.                                                                |  Defaults to original language    |
|  --proxy                   | Proxy URI to use. If a 2-letter country is provided, it will try get a proxy from the config. |  None                             |
|  -A, --audio-only          | Only download audio tracks.                                                                   |  False                            |
|  -S, --subs-only           | Only download subtitle tracks.                                                                |  False                            |
|  -C, --chapters-only       | Only download chapters.                                                                       |  False                            |
|  -ns, --no-subs            | Do not download subtitle tracks.                                                              |  False                            |
|  -na, --no-audio           | Do not download audio tracks.                                                                 |  False                            |
|  -nv, --no-video           | Do not download video tracks.                                                                 |  False                            |
|  -nc, --no-chapters        | Do not download chapters tracks.                                                              |  False                            |
|  -ad, --audio-description  | Download audio description tracks.                                                            |  False                            |
|  --list                    | Skip downloading and list available tracks and what tracks would have been downloaded.        |  False                            |
|  --selected                | List selected tracks and what tracks are downloaded.                                          |  False                            |
|  --cdm                     | Override the CDM that will be used for decryption.                                            |  None                             |
|  --keys                    | Skip downloading, retrieve the decryption keys (via CDM or Key Vaults) and print them.        |  False                            |
|  --cache                   | Disable the use of the CDM and only retrieve decryption keys from Key Vaults. If a needed key is unable to be retrieved from any Key Vaults, the title is skipped.|  False  |
|  --no-cache                | Disable the use of Key Vaults and only retrieve decryption keys from the CDM.                 |  False                            |
|  --no-proxy                | Force disable all proxy use.                                                                  |  False                            |
|  -nm, --no-mux             | Do not mux the downloaded and decrypted tracks.                                               |  False                            |
|  --mux                     | Force muxing when using --audio-only/--subs-only/--chapters-only.                             |  False                            |
|  -?, -h, --help            | Show this message and exit.                                                                   |                                   |


COMMAND :-

| Alaias |  Command      | Service Link                               |
|--------|---------------|--------------------------------------------|
| AMZN   |  Amazon       | https://amazon.com, https://primevideo.com |
| ATVP   |  AppleTVPlus  | https://tv.apple.com                       |
| MAX    |  Max          | https://max.com                            |
| NF     |  Netflix      | https://netflix.com                        |
  
### Amazon Specific Options

Usage: vt.cmd AMZN [OPTIONS] [TITLE]

  Service code for Amazon VOD (https://amazon.com) and Amazon Prime Video (https://primevideo.com).

  Authorization: Cookies
  
  Security: 
  ```
  UHD@L1/SL3000
  FHD@L3(ChromeCDM)/SL2000
  SD@L3

  Certain SL2000 can do UHD
  ```
  Maintains their own license server like Netflix, be cautious.
  
  Region is chosen automatically based on domain extension found in cookies.
  Prime Video specific code will be run if the ASIN is detected to be a prime video variant.
  Use 'Amazon Video ASIN Display' for Tampermonkey addon for ASIN
  https://greasyfork.org/en/scripts/381997-amazon-video-asin-display

  vt dl --list -z uk -q 1080 Amazon B09SLGYLK8

Below flags to be passed after the `AMZN` or `Amazon` keyword in command.

|  Command Line Switch                | Description                                                                                         |
|-------------------------------------|-----------------------------------------------------------------------------------------------------|
|  -b, --bitrate    | Video Bitrate Mode to download in. CVBR=Constrained Variable Bitrate, CBR=Constant Bitrate. (CVBR or CBR or CVBR+CBR) |
|  -c, --cdn        | CDN to download from, defaults to the CDN with the highest weight set by Amazon.                                      |
|  -vq, --vquality  | Manifest quality to request. (SD or HD or UHD)                                                                        |
|  -s, --single     | Force single episode/season instead of getting series ASIN.                                                           |
|  -am, --amanifest | Manifest to use for audio. Defaults to H265 if the video manifest is missing 640k audio. (CVBR or CBR or H265)        |
|  -aq, --aquality  | Manifest quality to request for audio. Defaults to the same as --quality. (SD or HD or UHD)                           |
|  -ism, --ism      | Set manifest override to SmoothStreaming. Defaults to DASH w/o this flag.                                             |
|  -?, -h, --help   | Show this message and exit.                                                                                           |

To get Atmos/UHD/4k with Amazon, navigate to -

```
https://www.primevideo.com/region/eu/ontv/code?ref_=atv_auth_red_aft
```

Login and get to the code pair page. Extract cookies from that page using [Open Cookies.txt](https://chromewebstore.google.com/detail/open-cookiestxt/gdocmgbfkjnnpapoeobnolbbkoibbcif).

Save it to the path `vinetrimmer/Cookies/Amazon/default.txt`.

When caching cookies, use a profile without PIN. Otherwise it causes errors.

### Peacock 

 - PCOK bans leaked certs quickly (for 4k), be cautious.

### Example Command

Amazon Example:

```bash
poetry run vt dl -al en -sl en --selected -q 2160 -r HDR -w S01E18-S01E25 AMZN -b CBR --ism 0IQZZIJ6W6TT2CXPT6ZOZYX396
```

Above command:
 - gets english subtitles + audio,
 - selects the HDR + 4K track,
 - gets episodes from S01E18 to S01E25 from Amazon
 - with CBR bitrate,
 - tries to force ISM
 - and the title-ID is 0IQZZIJ6W6TT2CXPT6ZOZYX396

AppleTV Example:

```bash
poetry run vt dl -al en -sl en --list -q 720 --proxy http://192.168.0.99:9766 -w S01E01 ATVP umc.cmc.1nfdfd5zlk05fo1bwwetzldy3
```

Above command:
 - gets english subtitles + audio,
 - lists all possible qualities,
 - selects 720p video track,
 - uses the proxy for licensing,
 - gets the first episode of first season (i.e S01E01)
 - of the title umc.cmc.1nfdfd5zlk05fo1bwwetzldy3


## Proxy
I recommend [Windscribe](https://windscribe.com/). You can sign up, getting 10 GB of traffic credit every month for free. We use the VPN for everything except downloading video/audio. 
Tested so far on Amazon, AppleTVPlus, Max.

### Steps:
1. For each service, within get_tracks() function we do this below.
    ```python
    for track in tracks:
        track.needs_proxy = False
    ```
    
    This flag signals that this track does not need a proxy and a proxy will not be passed to downloader even if proxy given in CLI options.

2. Download Windscribe app and install it.

3. Go to `Options` -> `Connection` -> `Split Tunneling`. Enable it.
   
    Set `Mode` as `Inclusive`.

5. Go to `Options` -> `Connection` -> `Proxy Gateway`. Enable it. Select `Proxy Type` as `HTTP`.
   
    Copy the `IP` field (will look something like `192.168.0.141:9766`)

    Pass above copied to Vinetrimmer with the proxy flag like below.

    ```bash
    ...(other flags)... --proxy http://192.168.0.141:9766 .......
    ```

## Other
 - For `--keys` to work with ATVP you need to pass the `--no-subs` flag also
 - Nuikta compile is an option to run on various linux distributions.
 - Errors arise when running VT within Docker or Conda like python distributions. Make sure to use proper python3.
 - To use programs in `scripts` folder, first activate venv then, then - 
      ```bash
      poetry run python scripts/ParseKeybox.py
      ```
