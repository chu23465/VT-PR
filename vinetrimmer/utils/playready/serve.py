import base64
from pathlib import Path
from typing import Any, Optional, Union

from aiohttp.typedefs import Handler
from aiohttp import web

from . import __version__, PSSH
from .cdm import Cdm
from .device import Device

from .exceptions import (InvalidSession, TooManySessions, InvalidLicense, InvalidPssh)

routes = web.RouteTableDef()


async def _startup(app: web.Application) -> None:
    app["cdms"] = {}
    app["config"]["devices"] = {
        path.stem: path
        for x in app["config"]["devices"]
        for path in [Path(x)]
    }
    for device in app["config"]["devices"].values():
        if not device.is_file():
            raise FileNotFoundError(f"Device file does not exist: {device}")


async def _cleanup(app: web.Application) -> None:
    app["cdms"].clear()
    del app["cdms"]
    app["config"].clear()
    del app["config"]


@routes.get("/")
async def ping(_: Any) -> web.Response:
    return web.json_response({
        "status": 200,
        "message": "Pong!"
    })


@routes.get("/{device}/open")
async def open_(request: web.Request) -> web.Response:
    secret_key = request.headers["X-Secret-Key"]
    device_name = request.match_info["device"]
    user = request.app["config"]["users"][secret_key]

    if device_name not in user["devices"] or device_name not in request.app["config"]["devices"]:
        # we don't want to be verbose with the error as to not reveal device names
        # by trial and error to users that are not authorized to use them
        return web.json_response({
            "status": 403,
            "message": f"Device '{device_name}' is not found or you are not authorized to use it."
        }, status=403)

    cdm: Optional[Cdm] = request.app["cdms"].get((secret_key, device_name))
    if not cdm:
        device = Device.load(request.app["config"]["devices"][device_name])
        cdm = request.app["cdms"][(secret_key, device_name)] = Cdm.from_device(device)

    try:
        session_id = cdm.open()
    except TooManySessions as e:
        return web.json_response({
            "status": 400,
            "message": str(e)
        }, status=400)

    return web.json_response({
        "status": 200,
        "message": "Success",
        "data": {
            "session_id": session_id.hex(),
            "device": {
                "security_level": cdm.security_level
            }
        }
    })


@routes.get("/{device}/close/{session_id}")
async def close(request: web.Request) -> web.Response:
    secret_key = request.headers["X-Secret-Key"]
    device_name = request.match_info["device"]
    session_id = bytes.fromhex(request.match_info["session_id"])

    cdm: Optional[Cdm] = request.app["cdms"].get((secret_key, device_name))
    if not cdm:
        return web.json_response({
            "status": 400,
            "message": f"No Cdm session for {device_name} has been opened yet. No session to close."
        }, status=400)

    try:
        cdm.close(session_id)
    except InvalidSession:
        return web.json_response({
            "status": 400,
            "message": f"Invalid Session ID '{session_id.hex()}', it may have expired."
        }, status=400)

    return web.json_response({
        "status": 200,
        "message": f"Successfully closed Session '{session_id.hex()}'."
    })


@routes.post("/{device}/get_license_challenge")
async def get_license_challenge(request: web.Request) -> web.Response:
    secret_key = request.headers["X-Secret-Key"]
    device_name = request.match_info["device"]

    body = await request.json()
    for required_field in ("session_id", "init_data"):
        if not body.get(required_field):
            return web.json_response({
                "status": 400,
                "message": f"Missing required field '{required_field}' in JSON body."
            }, status=400)

    # get session id
    session_id = bytes.fromhex(body["session_id"])

    # get cdm
    cdm: Optional[Cdm] = request.app["cdms"].get((secret_key, device_name))
    if not cdm:
        return web.json_response({
            "status": 400,
            "message": f"No Cdm session for {device_name} has been opened yet. No session to use."
        }, status=400)

    # get init data
    init_data = body["init_data"]

    if not init_data.startswith("<WRMHEADER"):
        try:
            pssh = PSSH(init_data)
            wrm_headers = pssh.get_wrm_headers(downgrade_to_v4=True)
            if wrm_headers:
                init_data = wrm_headers[0]
        except InvalidPssh as e:
            return web.json_response({
                "status": 500,
                "message": f"Unable to parse base64 PSSH, {e}"
            }, status=500)

    # get challenge
    try:
        license_request = cdm.get_license_challenge(
            session_id=session_id,
            wrm_header=init_data,
        )
    except InvalidSession:
        return web.json_response({
            "status": 400,
            "message": f"Invalid Session ID '{session_id.hex()}', it may have expired."
        }, status=400)
    except Exception as e:
        return web.json_response({
            "status": 500,
            "message": f"Error, {e}"
        }, status=500)

    return web.json_response({
        "status": 200,
        "message": "Success",
        "data": {
            "challenge": license_request
        }
    }, status=200)


@routes.post("/{device}/parse_license")
async def parse_license(request: web.Request) -> web.Response:
    secret_key = request.headers["X-Secret-Key"]
    device_name = request.match_info["device"]

    body = await request.json()
    for required_field in ("session_id", "license_message"):
        if not body.get(required_field):
            return web.json_response({
                "status": 400,
                "message": f"Missing required field '{required_field}' in JSON body."
            }, status=400)

    # get session id
    session_id = bytes.fromhex(body["session_id"])

    # get cdm
    cdm: Optional[Cdm] = request.app["cdms"].get((secret_key, device_name))
    if not cdm:
        return web.json_response({
            "status": 400,
            "message": f"No Cdm session for {device_name} has been opened yet. No session to use."
        }, status=400)

    # parse the license message
    try:
        cdm.parse_license(session_id, body["license_message"])
    except InvalidSession:
        return web.json_response({
            "status": 400,
            "message": f"Invalid Session ID '{session_id.hex()}', it may have expired."
        }, status=400)
    except InvalidLicense as e:
        return web.json_response({
            "status": 400,
            "message": f"Invalid License, {e}"
        }, status=400)
    except Exception as e:
        return web.json_response({
            "status": 500,
            "message": f"Error, {e}"
        }, status=500)

    return web.json_response({
        "status": 200,
        "message": "Successfully parsed and loaded the Keys from the License message."
    })


@routes.post("/{device}/get_keys")
async def get_keys(request: web.Request) -> web.Response:
    secret_key = request.headers["X-Secret-Key"]
    device_name = request.match_info["device"]

    body = await request.json()
    for required_field in ("session_id",):
        if not body.get(required_field):
            return web.json_response({
                "status": 400,
                "message": f"Missing required field '{required_field}' in JSON body."
            }, status=400)

    # get session id
    session_id = bytes.fromhex(body["session_id"])

    # get cdm
    cdm = request.app["cdms"].get((secret_key, device_name))
    if not cdm:
        return web.json_response({
            "status": 400,
            "message": f"No Cdm session for {device_name} has been opened yet. No session to use."
        }, status=400)

    # get keys
    try:
        keys = cdm.get_keys(session_id)
    except InvalidSession:
        return web.json_response({
            "status": 400,
            "message": f"Invalid Session ID '{session_id.hex()}', it may have expired."
        }, status=400)
    except Exception as e:
        return web.json_response({
            "status": 500,
            "message": f"Error, {e}"
        }, status=500)

    # get the keys in json form
    keys_json = [
        {
            "key_id": key.key_id.hex,
            "key": key.key.hex(),
            "type": key.key_type.value,
            "cipher_type": key.cipher_type.value,
            "key_length": key.key_length,
        }
        for key in keys
    ]

    return web.json_response({
        "status": 200,
        "message": "Success",
        "data": {
            "keys": keys_json
        }
    })


@web.middleware
async def authentication(request: web.Request, handler: Handler) -> web.Response:
    secret_key = request.headers.get("X-Secret-Key")

    if request.path != "/" and not secret_key:
        request.app.logger.debug(f"{request.remote} did not provide authorization.")
        response = web.json_response({
            "status": "401",
            "message": "Secret Key is Empty."
        }, status=401)
    elif request.path != "/" and secret_key not in request.app["config"]["users"]:
        request.app.logger.debug(f"{request.remote} failed authentication with '{secret_key}'.")
        response = web.json_response({
            "status": "401",
            "message": "Secret Key is Invalid, the Key is case-sensitive."
        }, status=401)
    else:
        try:
            response = await handler(request)  # type: ignore[assignment]
        except web.HTTPException as e:
            request.app.logger.error(f"An unexpected error has occurred, {e}")
            response = web.json_response({
                "status": 500,
                "message": e.reason
            }, status=500)

    response.headers.update({
        "Server": f"https://github.com/ready-dl/pyplayready serve v{__version__}"
    })

    return response


def run(config: dict, host: Optional[Union[str, web.HostSequence]] = None, port: Optional[int] = None) -> None:
    app = web.Application(middlewares=[authentication])
    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)
    app.add_routes(routes)
    app["config"] = config
    web.run_app(app, host=host, port=port)
