from construct import Struct, Const, Int8ub, Bytes, this, Int32ub, Switch, Embedded


class DeviceStructs:
    magic = Const(b"PRD")

    # was never in production
    v1 = Struct(
        "group_key_length" / Int32ub,
        "group_key" / Bytes(this.group_key_length),
        "group_certificate_length" / Int32ub,
        "group_certificate" / Bytes(this.group_certificate_length)
    )

    v2 = Struct(
        "group_certificate_length" / Int32ub,
        "group_certificate" / Bytes(this.group_certificate_length),
        "encryption_key" / Bytes(96),
        "signing_key" / Bytes(96),
    )

    v3 = Struct(
        "group_key" / Bytes(96),
        "encryption_key" / Bytes(96),
        "signing_key" / Bytes(96),
        "group_certificate_length" / Int32ub,
        "group_certificate" / Bytes(this.group_certificate_length),
    )

    prd = Struct(
        "signature" / magic,
        "version" / Int8ub,
        Embedded(Switch(
            lambda ctx: ctx.version,
            {
                1: v1,
                2: v2,
                3: v3
            }
        ))
    )
