import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
import requests
from Crypto.Random import get_random_bytes

from . import __version__
from .bcert import CertificateChain, Certificate
from .cdm import Cdm
from .device import Device
from .ecc_key import ECCKey
from .exceptions import OutdatedDevice
from .pssh import PSSH


@click.group(invoke_without_command=True)
@click.option("-v", "--version", is_flag=True, default=False, help="Print version information.")
@click.option("-d", "--debug", is_flag=True, default=False, help="Enable DEBUG level logs.")
def main(version: bool, debug: bool) -> None:
    """Python PlayReady CDM implementation"""
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    log = logging.getLogger()

    current_year = datetime.now().year
    copyright_years = f"2024-{current_year}"

    log.info("pyplayready version %s Copyright (c) %s DevLARLEY, Erevoc, DevataDev", __version__, copyright_years)
    log.info("https://github.com/ready-dl/pyplayready")
    log.info("Run 'pyplayready --help' for help")
    if version:
        return


@main.command(name="license")
@click.argument("device_path", type=Path)
@click.argument("pssh", type=PSSH)
@click.argument("server", type=str)
def license_(device_path: Path, pssh: PSSH, server: str) -> None:
    """
    Make a License Request to a server using a given PSSH
    Will return a list of all keys within the returned license

    Only works for standard license servers that don't use any license wrapping
    """
    log = logging.getLogger("license")

    device = Device.load(device_path)
    log.info(f"Loaded Device: {device.get_name()}")

    cdm = Cdm.from_device(device)
    log.info("Loaded CDM")

    session_id = cdm.open()
    log.info("Opened Session")

    challenge = cdm.get_license_challenge(session_id, pssh.get_wrm_headers(downgrade_to_v4=True)[0])
    log.info("Created License Request (Challenge)")
    log.debug(challenge)

    license_res = requests.post(
        url=server,
        headers={
            'Content-Type': 'text/xml; charset=UTF-8',
        },
        data=challenge
    )

    if license_res.status_code != 200:
        log.error(f"Failed to send challenge: [{license_res.status_code}] {license_res.text}")
        return

    licence = license_res.text
    log.info("Got License Message")
    log.debug(licence)

    cdm.parse_license(session_id, licence)
    log.info("License Parsed Successfully")

    for key in cdm.get_keys(session_id):
        log.info(f"{key.key_id.hex}:{key.key.hex()}")

    cdm.close(session_id)
    log.info("Clossed Session")


@main.command()
@click.argument("device", type=Path)
@click.pass_context
def test(ctx: click.Context, device: Path) -> None:
    """
    Test the CDM code by getting Content Keys for the Tears Of Steel demo on the Playready Test Server.
    https://testweb.playready.microsoft.com/Content/Content2X
    + DASH Manifest URL: https://test.playready.microsoft.com/media/profficialsite/tearsofsteel_4k.ism/manifest.mpd
    + MSS Manifest URL: https://test.playready.microsoft.com/media/profficialsite/tearsofsteel_4k.ism.smoothstreaming/manifest

    The device argument is a Path to a Playready Device (.prd) file which contains the device's group key and
    group certificate.
    """
    pssh = PSSH(
        "AAADfHBzc2gAAAAAmgTweZhAQoarkuZb4IhflQAAA1xcAwAAAQABAFIDPABXAFIATQBIAEUAQQBEAEUAUgAgAHgAbQBsAG4AcwA9ACIAaAB0AH"
        "QAcAA6AC8ALwBzAGMAaABlAG0AYQBzAC4AbQBpAGMAcgBvAHMAbwBmAHQALgBjAG8AbQAvAEQAUgBNAC8AMgAwADAANwAvADAAMwAvAFAAbABh"
        "AHkAUgBlAGEAZAB5AEgAZQBhAGQAZQByACIAIAB2AGUAcgBzAGkAbwBuAD0AIgA0AC4AMAAuADAALgAwACIAPgA8AEQAQQBUAEEAPgA8AFAAUg"
        "BPAFQARQBDAFQASQBOAEYATwA+ADwASwBFAFkATABFAE4APgAxADYAPAAvAEsARQBZAEwARQBOAD4APABBAEwARwBJAEQAPgBBAEUAUwBDAFQA"
        "UgA8AC8AQQBMAEcASQBEAD4APAAvAFAAUgBPAFQARQBDAFQASQBOAEYATwA+ADwASwBJAEQAPgA0AFIAcABsAGIAKwBUAGIATgBFAFMAOAB0AE"
        "cAawBOAEYAVwBUAEUASABBAD0APQA8AC8ASwBJAEQAPgA8AEMASABFAEMASwBTAFUATQA+AEsATABqADMAUQB6AFEAUAAvAE4AQQA9ADwALwBD"
        "AEgARQBDAEsAUwBVAE0APgA8AEwAQQBfAFUAUgBMAD4AaAB0AHQAcABzADoALwAvAHAAcgBvAGYAZgBpAGMAaQBhAGwAcwBpAHQAZQAuAGsAZQ"
        "B5AGQAZQBsAGkAdgBlAHIAeQAuAG0AZQBkAGkAYQBzAGUAcgB2AGkAYwBlAHMALgB3AGkAbgBkAG8AdwBzAC4AbgBlAHQALwBQAGwAYQB5AFIA"
        "ZQBhAGQAeQAvADwALwBMAEEAXwBVAFIATAA+ADwAQwBVAFMAVABPAE0AQQBUAFQAUgBJAEIAVQBUAEUAUwA+ADwASQBJAFMAXwBEAFIATQBfAF"
        "YARQBSAFMASQBPAE4APgA4AC4AMQAuADIAMwAwADQALgAzADEAPAAvAEkASQBTAF8ARABSAE0AXwBWAEUAUgBTAEkATwBOAD4APAAvAEMAVQBT"
        "AFQATwBNAEEAVABUAFIASQBCAFUAVABFAFMAPgA8AC8ARABBAFQAQQA+ADwALwBXAFIATQBIAEUAQQBEAEUAUgA+AA=="
    )

    license_server = "https://test.playready.microsoft.com/service/rightsmanager.asmx?cfg=(persist:false,sl:2000)"

    ctx.invoke(
        license_,
        device_path=device,
        pssh=pssh,
        server=license_server
    )


@main.command()
@click.option("-k", "--group_key", type=Path, required=True, help="Device ECC private group key")
@click.option("-c", "--group_certificate", type=Path, required=True, help="Device group certificate chain")
@click.option("-o", "--output", type=Path, default=None, help="Output Path or Directory")
@click.pass_context
def create_device(
    ctx: click.Context,
    group_key: Path,
    group_certificate: Path,
    output: Optional[Path] = None
) -> None:
    """Create a Playready Device (.prd) file from an ECC private group key and group certificate chain"""
    if not group_key.is_file():
        raise click.UsageError("group_key: Not a path to a file, or it doesn't exist.", ctx)
    if not group_certificate.is_file():
        raise click.UsageError("group_certificate: Not a path to a file, or it doesn't exist.", ctx)

    log = logging.getLogger("create-device")

    encryption_key = ECCKey.generate()
    signing_key = ECCKey.generate()

    group_key = ECCKey.load(group_key)
    certificate_chain = CertificateChain.load(group_certificate)

    new_certificate = Certificate.new_leaf_cert(
        cert_id=get_random_bytes(16),
        security_level=certificate_chain.get_security_level(),
        client_id=get_random_bytes(16),
        signing_key=signing_key,
        encryption_key=encryption_key,
        group_key=group_key,
        parent=certificate_chain
    )
    certificate_chain.prepend(new_certificate)

    device = Device(
        group_key=group_key.dumps(),
        encryption_key=encryption_key.dumps(),
        signing_key=signing_key.dumps(),
        group_certificate=certificate_chain.dumps(),
    )

    if output and output.suffix:
        if output.suffix.lower() != ".prd":
            log.warning(f"Saving PRD with the file extension '{output.suffix}' but '.prd' is recommended.")
        out_path = output
    else:
        out_dir = output or Path.cwd()
        out_path = out_dir / f"{device.get_name()}.prd"

    if out_path.exists():
        log.error(f"A file already exists at the path '{out_path}', cannot overwrite.")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(device.dumps())

    log.info("Created Playready Device (.prd) file, %s", out_path.name)
    log.info(" + Security Level: %s", device.security_level)
    log.info(" + Group Key: %s bytes", len(device.group_key.dumps()))
    log.info(" + Encryption Key: %s bytes", len(device.encryption_key.dumps()))
    log.info(" + Signing Key: %s bytes", len(device.signing_key.dumps()))
    log.info(" + Group Certificate: %s bytes", len(device.group_certificate.dumps()))
    log.info(" + Saved to: %s", out_path.absolute())


@main.command()
@click.argument("prd_path", type=Path)
@click.option("-o", "--output", type=Path, default=None, help="Output Path or Directory")
@click.pass_context
def reprovision_device(ctx: click.Context, prd_path: Path, output: Optional[Path] = None) -> None:
    """
    Reprovision a Playready Device (.prd) by creating a new leaf certificate and new encryption/signing keys.
    Will override the device if an output path or directory is not specified

    Only works on PRD Devices of v3 or higher
    """
    if not prd_path.is_file():
        raise click.UsageError("prd_path: Not a path to a file, or it doesn't exist.", ctx)

    log = logging.getLogger("reprovision-device")
    log.info("Reprovisioning Playready Device (.prd) file, %s", prd_path.name)

    device = Device.load(prd_path)

    if device.group_key is None:
        raise OutdatedDevice("Device does not support reprovisioning, re-create it or use a Device with a version of 3 or higher")

    device.group_certificate.remove(0)

    encryption_key = ECCKey.generate()
    signing_key = ECCKey.generate()

    device.encryption_key = encryption_key
    device.signing_key = signing_key

    new_certificate = Certificate.new_leaf_cert(
        cert_id=get_random_bytes(16),
        security_level=device.group_certificate.get_security_level(),
        client_id=get_random_bytes(16),
        signing_key=signing_key,
        encryption_key=encryption_key,
        group_key=device.group_key,
        parent=device.group_certificate
    )
    device.group_certificate.prepend(new_certificate)

    if output and output.suffix:
        if output.suffix.lower() != ".prd":
            log.warning(f"Saving PRD with the file extension '{output.suffix}' but '.prd' is recommended.")
        out_path = output
    else:
        out_path = prd_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(device.dumps())

    log.info("Reprovisioned Playready Device (.prd) file, %s", out_path.name)


@main.command()
@click.argument("prd_path", type=Path)
@click.option("-o", "--out_dir", type=Path, default=None, help="Output Directory")
@click.pass_context
def export_device(ctx: click.Context, prd_path: Path, out_dir: Optional[Path] = None) -> None:
    """
    Export a Playready Device (.prd) file to a Group Key and Group Certificate
    If an output directory is not specified, it will be stored in the current working directory
    """
    if not prd_path.is_file():
        raise click.UsageError("prd_path: Not a path to a file, or it doesn't exist.", ctx)

    log = logging.getLogger("export-device")
    log.info("Exporting Playready Device (.prd) file, %s", prd_path.stem)

    if not out_dir:
        out_dir = Path.cwd()

    out_path = out_dir / prd_path.stem
    if out_path.exists():
        if any(out_path.iterdir()):
            log.error("Output directory is not empty, cannot overwrite.")
            return
        else:
            log.warning("Output directory already exists, but is empty.")
    else:
        out_path.mkdir(parents=True)

    device = Device.load(prd_path)

    log.info(f"SL{device.security_level} {device.get_name()}")
    log.info(f"Saving to: {out_path}")

    if device.group_key:
        group_key_path = out_path / "zgpriv.dat"
        group_key_path.write_bytes(device.group_key.dumps())
        log.info("Exported Group Key as zgpriv.dat")
    else:
        log.warning("Cannot export zgpriv.dat, as v2 devices do not save the group key")

    # remove leaf cert to unprovision it
    device.group_certificate.remove(0)

    client_id_path = out_path / "bgroupcert.dat"
    client_id_path.write_bytes(device.group_certificate.dumps())
    log.info("Exported Group Certificate to bgroupcert.dat")


@main.command("serve", short_help="Serve your local CDM and Playready Devices Remotely.")
@click.argument("config_path", type=Path)
@click.option("-h", "--host", type=str, default="127.0.0.1", help="Host to serve from.")
@click.option("-p", "--port", type=int, default=7723, help="Port to serve from.")
def serve_(config_path: Path, host: str, port: int) -> None:
    """
    Serve your local CDM and Playready Devices Remotely.

    [CONFIG] is a path to a serve config file.
    See `serve.example.yml` for an example config file.

    Host as 127.0.0.1 may block remote access even if port-forwarded.
    Instead, use 0.0.0.0 and ensure the TCP port you choose is forwarded.
    """
    from pyplayready import serve
    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf8"))
    serve.run(config, host, port)
