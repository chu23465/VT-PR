#!/usr/bin/env python3

import argparse
import base64

import yaml

from vinetrimmer.utils.widevine.protos.widevine_pb2 import ClientIdentificationRaw

parser = argparse.ArgumentParser("Widevine Client ID building tool.")
parser.add_argument("-q", "--quiet",
                    help="do not print the generated client id",
                    action="store_true")
parser.add_argument("-c", "--config",
                    help="configuration yaml file",
                    default="config.yml")
parser.add_argument("-o", "--output",
                    default="device_client_id_blob",
                    help="output filename")
args = parser.parse_args()

with open(args.config) as fd:
    config = yaml.safe_load(fd)

with open(config["token"], "rb") as fd:
    token = fd.read()

ci = ClientIdentificationRaw()
ci.Type = ClientIdentificationRaw.DEVICE_CERTIFICATE
ci.Token = token

for name, value in config["client_info"].items():
    nv = ci.ClientInfo.add()
    nv.Name = name
    if name == "device_id":
        value = base64.b64decode(value)
    nv.Value = value

capabilities = ClientIdentificationRaw.ClientCapabilities()
caps = config["capabilities"]
if "client_token" in caps:
    capabilities.ClientToken = caps["client_token"]
if "session_token" in caps:
    capabilities.SessionToken = caps["session_token"]
if "video_resolution_constraints" in caps:
    capabilities.VideoResolutionConstraints = caps["video_resolution_constraints"]
if "max_hdcp_version" in caps:
    max_hdcp_version = caps["max_hdcp_version"]
    if str(max_hdcp_version).isdigit():
        max_hdcp_version = int(max_hdcp_version)
    else:
        max_hdcp_version = ClientIdentificationRaw.ClientCapabilities.HdcpVersion.Value(max_hdcp_version)
    capabilities.MaxHdcpVersion = max_hdcp_version
if "oem_crypto_api_version" in caps:
    capabilities.OemCryptoApiVersion = int(caps["oem_crypto_api_version"])
# I have not seen any of the following in use:
if "anti_rollback_usage_table" in caps:
    capabilities.AntiRollbackUsageTable = caps["anti_rollback_usage_table"]
if "srm_version" in caps:
    capabilities.SrmVersion = int(caps["srm_version"])
if "can_update_srm" in caps:
    capabilities.ClientToken = caps["can_update_srm"]
# is it possible to refactor this?
if "supported_certificate_key_type" in caps:
    supported_certificate_key_type = caps["supported_certificate_key_type"]
    if str(supported_certificate_key_type).isdigit():
        supported_certificate_key_type = int(supported_certificate_key_type)
    else:
        supported_certificate_key_type = ClientIdentificationRaw.ClientCapabilities.CertificateKeyType.Value(
            supported_certificate_key_type
        )
    capabilities.SupportedCertificateKeyType.append(supported_certificate_key_type)
ci._ClientCapabilities.CopyFrom(capabilities)

if not args.quiet:
    print(ci)

with open(args.output, "wb") as fd:
    fd.write(ci.SerializeToString())
