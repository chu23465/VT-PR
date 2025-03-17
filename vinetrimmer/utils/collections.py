import itertools
from typing import Iterable, Sequence


def as_lists(*args):
    """Convert any input objects to list objects."""
    for item in args:
        yield item if isinstance(item, list) else [item]


def as_list(*args):
    """
    Convert any input objects to a single merged list object.

    Example:
    >>> as_list('foo', ['buzz', 'bizz'], 'bazz', 'bozz', ['bar'], ['bur'])
    ['foo', 'buzz', 'bizz', 'bazz', 'bozz', 'bar', 'bur']
    """
    if args == (None,):
        return []
    return list(itertools.chain.from_iterable(as_lists(*args)))


def flatten(items, ignore_types=str):
    """
    Flatten items recursively.

    Example:
    >>> list(flatten(["foo", [["bar", ["buzz", [""]], "bee"]]]))
    ['foo', 'bar', 'buzz', '', 'bee']
    >>> list(flatten("foo"))
    ['foo']
    >>> list(flatten({1}, set))
    [{1}]
    """
    if isinstance(items, (Iterable, Sequence)) and not isinstance(items, ignore_types):
        for i in items:
            yield from flatten(i, ignore_types)
    else:
        yield items


def merge_dict(*dicts):
    """Recursively merge dicts into dest in-place."""
    dest = dicts[0]
    for d in dicts[1:]:
        for key, value in d.items():
            if isinstance(value, dict):
                node = dest.setdefault(key, {})
                merge_dict(node, value)
            else:
                dest[key] = value
