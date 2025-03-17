from langcodes import Language, closest_match

from vinetrimmer.constants import LANGUAGE_MAX_DISTANCE
from vinetrimmer.utils.widevine.cdm import Cdm  # noqa: F401
from vinetrimmer.utils.widevine.protos.widevine_pb2 import WidevineCencHeader  # noqa: F401
from vinetrimmer.vendor.pymp4.parser import Box


def get_boxes(data, box_type, as_bytes=False):
    """Scan a byte array for a wanted box, then parse and yield each find."""
    # using slicing to get to the wanted box is done because parsing the entire box and recursively
    # scanning through each box and its children often wouldn't scan far enough to reach the wanted box.
    # since it doesnt care what child box the wanted box is from, this works fine.
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("data must be bytes")
    while True:
        try:
            index = data.index(box_type)
        except ValueError:
            break
        if index < 0:
            break
        if index > 4:
            index -= 4  # size is before box type and is 4 bytes long
        data = data[index:]
        try:
            box = Box.parse(data)
        except IOError:
            # TODO: Does this miss any data we may need?
            break
        if as_bytes:
            box = Box.build(box)
        yield box


def is_close_match(language, languages):
    if not (language and languages and all(languages)):
        return False
    languages = list(map(str, [x for x in languages if x]))
    return closest_match(language, languages)[1] <= LANGUAGE_MAX_DISTANCE


def get_closest_match(language, languages):
    match, distance = closest_match(language, list(map(str, languages)))
    if distance > LANGUAGE_MAX_DISTANCE:
        return None
    return Language.get(match)


def try_get(obj, func):
    try:
        return func(obj)
    except (AttributeError, IndexError, KeyError, TypeError):
        return None
        
def short_hash(input):
    return base_encode(int(md5(input).hexdigest(), 16))
