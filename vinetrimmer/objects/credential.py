import hashlib
import re

import requests
import validators


class Credential:
    """Username (or Email) and Password Credential."""

    def __init__(self, username, password, extra=None):
        self.username = username
        self.password = password
        self.extra = extra
        self.sha1 = hashlib.sha1(self.dumps().encode()).hexdigest()

    def __bool__(self):
        return bool(self.username) and bool(self.password)

    def __str__(self):
        return self.dumps()

    def __repr__(self):
        return "{name}({items})".format(
            name=self.__class__.__name__,
            items=", ".join([f"{k}={repr(v)}" for k, v in self.__dict__.items()])
        )

    def dumps(self):
        """Return credential data as a string."""
        return f"{self.username}:{self.password}" + (f":{self.extra}" if self.extra else "")

    def dump(self, path):
        """Write credential data to a file."""
        with open(path, "w", encoding="utf-8") as fd:
            fd.write(self.dumps())

    @classmethod
    def loads(cls, text):
        """
        Load credential from a text string.

        Format: {username}:{password}
        Rules:
            Only one Credential must be in this text contents.
            All whitespace before and after all text will be removed.
            Any whitespace between text will be kept and used.
            The credential can be spanned across one or multiple lines as long as it
                abides with all the above rules and the format.

        Example that follows the format and rules:
            `\tJohnd\noe@gm\n\rail.com\n:Pass1\n23\n\r  \t  \t`
            >>>Credential(username='Johndoe@gmail.com', password='Pass123')
        """
        text = "".join([
            x.strip() for x in text.splitlines(keepends=False)
        ]).strip()
        credential = re.fullmatch(r"^([^:]+?):([^:]+?)(?::(.+))?$", text)
        if credential:
            return cls(*credential.groups())
        raise ValueError("No credentials found in text string. Expecting the format `username:password`")

    @classmethod
    def load(cls, uri, session=None):
        """
        Load Credential from a remote URL string or a local file path.
        Use Credential.loads() for loading from text content and seeing the rules and
        format expected to be found in the URIs contents.

        Parameters:
            uri: Remote URL string or a local file path.
            session: Python-requests session to use for Remote URL strings. This can be
                used to set custom Headers, Proxies, etc.
        """
        if validators.url(uri):
            # remote file
            return cls.loads((session or requests).get(uri).text)
        else:
            # local file
            with open(uri, encoding="utf-8") as fd:
                return cls.loads(fd.read())
