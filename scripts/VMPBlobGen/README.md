# VMPBlobGen

Notes on VMP:

- Android doesn't require (or use!) a VMP blob (the oemcrypto hardware backs it and HDCP controls the path)
- Chrome and WidevineCDM both have signature files. The widevinecdm.dll and chrome.exe sign both the signature files,
  then sign with the private key and inject to the license request in field 7, but you need a server cert to encrypt
  the challenge otherwise.
