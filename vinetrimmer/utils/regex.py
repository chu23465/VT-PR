import re


def find(pattern, string, group=None):
    if group:
        m = re.search(pattern, string)
        if m:
            return m.group(group)
    else:
        return next(iter(re.findall(pattern, string)), None)
