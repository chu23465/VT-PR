import asyncio
import contextlib
import os
import re
import shutil
import subprocess
import sys
import httpx
import pproxy
import requests
import yaml

from vinetrimmer import config
from vinetrimmer.utils.collections import as_list


def load_yaml(path):
    if not os.path.isfile(path):
        return {}
    with open(path) as fd:
        return yaml.safe_load(fd)


_ip_info = None


def get_ip_info(session=None, fresh=False):
    """Use extreme-ip-lookup.com to get IP location information."""
    global _ip_info

    if fresh or not _ip_info:
        # alternatives: http://www.geoplugin.net/json.gp, http://ip-api.com/json/, https://extreme-ip-lookup.com/json
        _ip_info = (session or httpx).get("http://ip-api.com/json/").json()

    return _ip_info


@contextlib.asynccontextmanager
async def start_pproxy(host, port, username, password):
    rerouted_proxy = "http://localhost:8081"
    server = pproxy.Server(rerouted_proxy)
    remote = pproxy.Connection(f"http+ssl://{host}:{port}#{username}:{password}")
    handler = await server.start_server(dict(rserver=[remote]))
    try:
        yield rerouted_proxy
    finally:
        handler.close()
        await handler.wait_closed()


def download_range(url, count, start=0, proxy=None):
    """Download n bytes without using the Range header due to support issues."""
    # TODO: Can this be done with Aria2c?
    executable = shutil.which("curl")
    if not executable:
        raise EnvironmentError("Track needs curl to download a chunk of data but wasn't found...")

    arguments = [
        executable,
        "-s",  # use -s instead of --no-progress-meter due to version requirements
        "-L",  # follow redirects, e.g. http->https
        "--proxy-insecure",  # disable SSL verification of proxy
        "--output", "-",  # output to stdout
        "--url", url
    ]
    if proxy:
        arguments.extend(["--proxy", proxy])

    curl = subprocess.Popen(
        arguments,
        stdout=subprocess.PIPE,
        stderr=open(os.devnull, "wb"),
        shell=False
    )
    buffer = b''
    location = -1
    while len(buffer) < count:
        stdout = curl.stdout
        data = b''
        if stdout:
            data = stdout.read(1)
        if len(data) > 0:
            location += len(data)
            if location >= start:
                buffer += data
        else:
            if curl.poll() is not None:
                break
    curl.kill()  # stop downloading
    return buffer


async def aria2c(uri, out, headers=None, proxy=None):
    """
    Downloads file(s) using Aria2(c).

    Parameters:
        uri: URL to download. If uri is a list of urls, they will be downloaded and
          concatenated into one file.
        out: The output file path to save to.
        headers: Headers to apply on aria2c.
        proxy: Proxy to apply on aria2c.
    """
    executable = shutil.which("aria2c") or shutil.which("aria2")
    if not executable:
        raise EnvironmentError("Aria2c executable not found...")

    arguments = [
        executable,
        "-c",  # Continue downloading a partially downloaded file
        "--remote-time",  # Retrieve timestamp of the remote file from the and apply if available
        "-o", os.path.basename(out),  # The file name of the downloaded file, relative to -d
        "-x", "16",  # The maximum number of connections to one server for each download
        "-j", "16",  # The maximum number of parallel downloads for every static (HTTP/FTP) URL
        "-s", "16",  # Download a file using N connections.
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--retry-wait", "5",  # Set the seconds to wait between retries.
        "--max-tries", "15",
        "--max-file-not-found", "15",
        "--summary-interval", "0",
        "--file-allocation", "none" if sys.platform == "win32" else "falloc",
        "--console-log-level", "warn",
        "--download-result", "hide"
    ]

    for option, value in config.config.aria2c.items():
        arguments.append(f"--{option.replace('_', '-')}={value}")

    for header, value in (headers or {}).items():
        if header.lower() == "accept-encoding":
            # we cannot set an allowed encoding, or it will return compressed
            # and the code is not set up to uncompress the data
            continue
        arguments.extend(["--header", f"{header}: {value}"])

    segmented = isinstance(uri, list)
    segments_dir = f"{out}_segments"

    if segmented:
        uri = "\n".join([
            f"{url}\n"
            f"\tdir={segments_dir}\n"
            f"\tout={i:08}.mp4"
            for i, url in enumerate(uri)
        ])

    if proxy:
        arguments.append("--all-proxy")
        if proxy.lower().startswith("https://"):
            auth, hostname = proxy[8:].split("@")
            async with start_pproxy(*hostname.split(":"), *auth.split(":")) as pproxy_:
                arguments.extend([pproxy_, "-d"])
                if segmented:
                    arguments.extend([segments_dir, "-i-"])
                    proc = await asyncio.create_subprocess_exec(*arguments, stdin=subprocess.PIPE)
                    await proc.communicate(as_list(uri)[0].encode("utf-8"))
                else:
                    arguments.extend([os.path.dirname(out), uri])
                    proc = await asyncio.create_subprocess_exec(*arguments)
                    await proc.communicate()
        else:
            arguments.append(proxy)

    try:
        if segmented:
            subprocess.run(
                arguments + ["-d", segments_dir, "-i-"],
                input=as_list(uri)[0],
                encoding="utf-8",
                check=True
            )
        else:
            subprocess.run(
                arguments + ["-d", os.path.dirname(out), uri],
                check=True
            )
    except subprocess.CalledProcessError:
        raise ValueError("Aria2c failed too many times, aborting")

    if segmented:
        # merge the segments together
        with open(out, "wb") as ofd:
            for file in sorted(os.listdir(segments_dir)):
                file = os.path.join(segments_dir, file)
                with open(file, "rb") as ifd:
                    data = ifd.read()
                # Apple TV+ needs this done to fix audio decryption
                data = re.sub(b"(tfhd\x00\x02\x00\x1a\x00\x00\x00\x01\x00\x00\x00)\x02", b"\\g<1>\x01", data)
                ofd.write(data)
                os.unlink(file)
        os.rmdir(segments_dir)

    print()


async def saldl(uri, out, headers=None, proxy=None):
    if headers:
        headers.update({k: v for k, v in headers.items() if k.lower() != "accept-encoding"})

    executable = shutil.which("saldl") or shutil.which("saldl-win64") or shutil.which("saldl-win32")
    if not executable:
        raise EnvironmentError("Saldl executable not found...")

    arguments = [
        executable,
        # "--no-status",
        "--skip-TLS-verification",
        "--resume",
        "--merge-in-order",
        "-c8",
        "--auto-size", "1",
        "-D", os.path.dirname(out),
        "-o", os.path.basename(out),
    ]

    if headers:
        arguments.extend([
            "--custom-headers",
            "\r\n".join([f"{k}: {v}" for k, v in headers.items()])
        ])

    if proxy:
        arguments.extend(["--proxy", proxy])

    if isinstance(uri, list):
        raise ValueError("Saldl code does not yet support multiple uri (e.g. segmented) downloads.")
    arguments.append(uri)

    try:
        subprocess.run(arguments, check=True)
    except subprocess.CalledProcessError:
        raise ValueError("Saldl failed too many times, aborting")

    print()
