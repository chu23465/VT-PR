class Key:
    def __init__(self, kid, key_type, key, permissions=None):
        self.kid = kid
        self.type = key_type
        self.key = key
        self.permissions = permissions or []

    def __repr__(self):
        return "{name}({items})".format(
            name=self.__class__.__name__,
            items=", ".join([f"{k}={repr(v)}" for k, v in self.__dict__.items()])
        )
