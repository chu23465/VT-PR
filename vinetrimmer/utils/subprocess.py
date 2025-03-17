import json
import subprocess


def ffprobe(uri):
    """Use ffprobe on the provided data to get stream information."""
    args = [
        "ffprobe",
        "-v", "quiet",
        "-of", "json",
        "-show_streams"
    ]
    if isinstance(uri, str):
        args.extend([
            "-f", "lavfi",
            "-i", "movie={}[out+subcc]".format(uri.replace("\\", '/').replace(":", "\\\\:"))
        ])
    elif isinstance(uri, bytes):
        args.append("pipe:")
    try:
        ff = subprocess.run(
            args,
            input=uri if isinstance(uri, bytes) else None,
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError:
        return {}
    return json.loads(ff.stdout.decode("utf-8"))
