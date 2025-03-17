# Most of these were taken from the old player JS.
# 40002 was inferred based on tests with actual keys.
DRMTODAY_RESPONSE_CODES = {
    "00000": "Success",
    "01000": "General Internal Error",
    "02000": "General Request Error",
    "03000": "General Request Authentication Error",
    "30000": "General DRM Error",
    "40000": "General Widevine Modular Error",
    "40001": "Widevine Device Certificate Revocation",
    "40002": "Widevine Device Certificate Serial Number Revocation",
    "41000": "General Widevine Classic Error",
    "42000": "General PlayReady Error",
    "43000": "General FairPlay Error",
    "44000": "General OMA Error",
    "44001": "OMA Device Registration Failed",
    "45000": "General CDRM Error",
    "45001": "CDRM Device Registration Failed",
    "70000": "General Output Protection Error",
    "70001": "All keys filtered by EOP settings",
    "80000": "General CSL Error",
    "80001": "Too many concurrent streams",
    "90000": "General GBL Error",
    "90001": "License delivery prohibited in your region"
}
