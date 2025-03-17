from abc import ABC

from construct import Subconstruct


class TellPlusSizeOf(Subconstruct, ABC):
    def __init__(self, subcon):
        super(TellPlusSizeOf, self).__init__(subcon)
        self.flagbuildnone = True

    def _parse(self, stream, context, path):
        return stream.tell() + self.subcon.sizeof(context=context)

    def _build(self, obj, stream, context, path):
        return b""

    def sizeof(self, context=None, **kw):
        return 0

class TellMinusSizeOf(Subconstruct, ABC):
    def __init__(self, subcon):
        super(TellMinusSizeOf, self).__init__(subcon)
        self.flagbuildnone = True

    def _parse(self, stream, context, path):
        return stream.tell() - self.subcon.sizeof(context=context)

    def _build(self, obj, stream, context, path):
        return b""

    def sizeof(self, context=None, **kw):
        return 0
