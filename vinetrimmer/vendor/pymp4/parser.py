#!/usr/bin/env python
"""
   Copyright 2016 beardypig

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
import logging
from uuid import UUID

from construct import *
from construct.lib import *

from .adapters import ISO6392TLanguageCode, MaskedInteger, UUIDBytes
from .subconstructs import TellPlusSizeOf, TellMinusSizeOf

log = logging.getLogger(__name__)

UNITY_MATRIX = [0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000]


# Header box

FileTypeBox = Struct(
    "major_brand" / PaddedString(4, "ascii"),
    "minor_version" / Int32ub,
    "compatible_brands" / GreedyRange(PaddedString(4, "ascii")),
)

SegmentTypeBox = Struct(
    "major_brand" / PaddedString(4, "ascii"),
    "minor_version" / Int32ub,
    "compatible_brands" / GreedyRange(PaddedString(4, "ascii")),
)

# Catch find boxes

RawBox = Struct(
    "data" / Default(GreedyBytes, b"")
)

FreeBox = Struct(
    "data" / GreedyBytes
)

SkipBox = Struct(
    "data" / GreedyBytes
)

# Movie boxes, contained in a moov Box

MovieHeaderBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "creation_time" / Default(Switch(this.version, {0: Int32ub, 1: Int64ub}), 0),
    "modification_time" / Default(Switch(this.version, {0: Int32ub, 1: Int64ub}), 0),
    "timescale" / Default(Int32ub, 10000000),
    "duration" / Switch(this.version, {0: Int32ub, 1: Int64ub}),
    "rate" / Default(Int32sb, 65536),
    "volume" / Default(Int16sb, 256),
    # below could be just Padding(10) but why not
    Const(0, Int16ub),
    Const(0, Int32ub),
    Const(0, Int32ub),
    "matrix" / Default(Int32sb[9], UNITY_MATRIX),
    "pre_defined" / Default(Int32ub[6], [0] * 6),
    "next_track_ID" / Default(Int32ub, 0xffffffff)
)

# Track boxes, contained in trak box

TrackHeaderBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 1),
    "creation_time" / Default(Switch(this.version, {0: Int32ub, 1: Int64ub}), 0),
    "modification_time" / Default(Switch(this.version, {0: Int32ub, 1: Int64ub}), 0),
    "track_ID" / Default(Int32ub, 1),
    Padding(4),
    "duration" / Default(Switch(this.version, {0: Int32ub, 1: Int64ub}), 0),
    Padding(8),
    "layer" / Default(Int16sb, 0),
    "alternate_group" / Default(Int16sb, 0),
    "volume" / Default(Int16sb, 0),
    Padding(2),
    "matrix" / Default(Array(9, Int32sb), UNITY_MATRIX),
    "width" / Default(Int32ub, 0),
    "height" / Default(Int32ub, 0),
)

HDSSegmentBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "info_version" / Int32ub,
    "flags" / BitStruct(
        Padding(1),
        "profile" / Flag,
        "live" / Flag,
        "update" / Flag,
        Padding(4)
    ),
    "time_scale" / Int32ub,
    "current_media_time" / Int64ub,
    "smpte_time_code_offset" / Int64ub,
    "movie_identifier" / CString("ascii"),
    "server_entry_table" / PrefixedArray(Int8ub, CString("ascii")),
    "quality_entry_table" / PrefixedArray(Int8ub, CString("ascii")),
    "drm_data" / CString("ascii"),
    "metadata" / CString("ascii"),
    "segment_run_table" / PrefixedArray(Int8ub, LazyBound(lambda x: Box)),
    "fragment_run_table" / PrefixedArray(Int8ub, LazyBound(lambda x: Box))
)

HDSSegmentRunBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "quality_entry_table" / PrefixedArray(Int8ub, CString("ascii")),
    "segment_run_enteries" / PrefixedArray(Int32ub, Struct(
        "first_segment" / Int32ub,
        "fragments_per_segment" / Int32ub
    ))
)

HDSFragmentRunBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / BitStruct(
        Padding(23),
        "update" / Flag
    ),
    "time_scale" / Int32ub,
    "quality_entry_table" / PrefixedArray(Int8ub, CString("ascii")),
    "fragment_run_enteries" / PrefixedArray(Int32ub, Struct(
        "first_fragment" / Int32ub,
        "first_fragment_timestamp" / Int64ub,
        "fragment_duration" / Int32ub,
        "discontinuity" / If(this.fragment_duration == 0, Int8ub)
    ))
)


# Boxes contained by Media Box

MediaHeaderBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Const(0, Int24ub),
    "creation_time" / IfThenElse(this.version == 1, Int64ub, Int32ub),
    "modification_time" / IfThenElse(this.version == 1, Int64ub, Int32ub),
    "timescale" / Int32ub,
    "duration" / IfThenElse(this.version == 1, Int64ub, Int32ub),
    "language" / ISO6392TLanguageCode(Int16ub),
    Padding(2, pattern=b"\x00")
)

HandlerReferenceBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    Padding(4, pattern=b"\x00"),
    "handler_type" / PaddedString(4, "ascii"),
    Padding(12, pattern=b"\x00"),  # Int32ub[3]
    "name" / CString("utf8")
)

# Boxes contained by Media Info Box

VideoMediaHeaderBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Const(1, Int24ub),
    "graphics_mode" / Default(Int16ub, 0),
    "opcolor" / Struct(
        "red" / Default(Int16ub, 0),
        "green" / Default(Int16ub, 0),
        "blue" / Default(Int16ub, 0),
    ),
)

DataEntryUrlBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / BitStruct(
        Padding(23), "self_contained" / Rebuild(Flag, ~this._.location)
    ),
    "location" / If(~this.flags.self_contained, CString("utf8")),
)

DataEntryUrnBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / BitStruct(
        Padding(23), "self_contained" / Rebuild(Flag, ~(this._.name & this._.location))
    ),
    "name" / If(this.flags == 0, CString("utf8")),
    "location" / If(this.flags == 0, CString("utf8")),
)

DataReferenceBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Default(Int24ub, 0),
    "data_entries" / PrefixedArray(Int32ub, LazyBound(lambda: Box)),
)

# Sample Table boxes (stbl)

MP4ASampleEntryBox = Struct(
    "version" / Default(Int16ub, 0),
    "revision" / Const(0, Int16ub),
    "vendor" / Const(0, Int32ub),
    "channels" / Default(Int16ub, 2),
    "bits_per_sample" / Default(Int16ub, 16),
    "compression_id" / Default(Int16sb, 0),
    "packet_size" / Const(0, Int16ub),
    "sampling_rate" / Int16ub,
    Padding(2)
)

AAVC = Struct(
    "version" / Const(1, Int8ub),
    "profile" / Int8ub,
    "compatibility" / Int8ub,
    "level" / Int8ub,
    "flags" / BitStruct(
        Padding(6, pattern=b'\x01'),
        "nal_unit_length_field" / Default(BitsInteger(2), 3),
    ),
    "sps" / Default(PrefixedArray(MaskedInteger(Int8ub), PascalString(Int16ub, "ascii")), []),
    "pps" / Default(PrefixedArray(Int8ub, PascalString(Int16ub, "ascii")), [])
)

HVCC = Struct(
    "version" / Const(1, Int8ub),
    "flags" / BitStruct(
        "profile_space" / BitsInteger(2),
        "general_tier_flag" / BitsInteger(1),
        "general_profile" / BitsInteger(5),
        "general_profile_compatibility_flags" / BitsInteger(32),
        "general_constraint_indicator_flags" / BitsInteger(48),
        "general_level" / BitsInteger(8),
        Padding(4, pattern=b'\xff'),
        "min_spatial_segmentation" / BitsInteger(12),
        Padding(6, pattern=b'\xff'),
        "parallelism_type" / BitsInteger(2),
        Padding(6, pattern=b'\xff'),
        "chroma_format" / BitsInteger(2),
        Padding(5, pattern=b'\xff'),
        "luma_bit_depth" / BitsInteger(3),
        Padding(5, pattern=b'\xff'),
        "chroma_bit_depth" / BitsInteger(3),
        "average_frame_rate" / BitsInteger(16),
        "constant_frame_rate" / BitsInteger(2),
        "num_temporal_layers" / BitsInteger(3),
        "temporal_id_nested" / BitsInteger(1),
        "nalu_length_size" / BitsInteger(2),
    ),
    # TODO: parse NALUs
    "raw_bytes" / GreedyBytes
)

AVC1SampleEntryBox = Struct(
    "version" / Default(Int16ub, 0),
    "revision" / Const(0, Int16ub),
    "vendor" / Default(PaddedString(4, "ascii"), "brdy"),
    "temporal_quality" / Default(Int32ub, 0),
    "spatial_quality" / Default(Int32ub, 0),
    "width" / Int16ub,
    "height" / Int16ub,
    "horizontal_resolution" / Default(Int16ub, 72),  # TODO: actually a fixed point decimal
    Padding(2),
    "vertical_resolution" / Default(Int16ub, 72),  # TODO: actually a fixed point decimal
    Padding(2),
    "data_size" / Const(0, Int32ub),
    "frame_count" / Default(Int16ub, 1),
    "compressor_name" / Default(PaddedString(32, "ascii"), None),
    "depth" / Default(Int16ub, 24),
    "color_table_id" / Default(Int16sb, -1),
    "avc_data" / Prefixed(Int32ub, Struct(
        "type" / PaddedString(4, "ascii"),
        "data" / Switch(this.type, {
            "avcC": AAVC,
            "hvcC": HVCC,
        }, GreedyBytes)
    ), includelength=True),
    "sample_info" / LazyBound(lambda _: GreedyRange(Box))
)

SampleEntryBox = Prefixed(Int32ub, Struct(
    "format" / PaddedString(4, "ascii"),
    Padding(6, pattern=b"\x00"),
    "data_reference_index" / Default(Int16ub, 1),
    "data" / Switch(this.format, {
        "ec-3": MP4ASampleEntryBox,
        "mp4a": MP4ASampleEntryBox,
        "enca": MP4ASampleEntryBox,
        "avc1": AVC1SampleEntryBox,
        "encv": AVC1SampleEntryBox,
        "wvtt": Struct("children" / LazyBound(lambda: GreedyRange(Box)))
    }, GreedyBytes)
), includelength=True)

BitRateBox = Struct(
    "bufferSizeDB" / Int32ub,
    "maxBitrate" / Int32ub,
    "avgBirate" / Int32ub,
)

SampleDescriptionBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Const(0, Int24ub),
    "entries" / PrefixedArray(Int32ub, LazyBound(lambda: Box))
)

SampleSizeBox = Struct(
    "version" / Int8ub,
    "flags" / Const(0, Int24ub),
    "sample_size" / Int32ub,
    "sample_count" / Int32ub,
    "entry_sizes" / If(this.sample_size == 0, Array(this.sample_count, Int32ub))
)

SampleSizeBox2 = Struct(
    "version" / Int8ub,
    "flags" / Const(0, Int24ub),
    Padding(3, pattern=b"\x00"),
    "field_size" / Int8ub,
    "sample_count" / Int24ub,
    "entries" / Array(this.sample_count, Struct(
        "entry_size" / LazyBound(lambda ctx: globals()["Int%dub" % ctx.field_size])
    ))
)

SampleDegradationPriorityBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
)

TimeToSampleBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "sample_count" / Int32ub,
        "sample_delta" / Int32ub,
    )), [])
)

SyncSampleBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "sample_number" / Int32ub,
    )), [])
)

CompositionOffsetBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Const(0, Int24ub),
    "entries" / Switch(this.version, {
        0: Default(PrefixedArray(Int32ub, Struct(
            "sample_count" / Int32ub,
            "sample_offset" / Int32ub,
        )), []),
        1: Default(PrefixedArray(Int32ub, Struct(
            "sample_count" / Int32ub,
            "sample_offset" / Int32sb,
        )), [])
    })
)

SampleToChunkBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "first_chunk" / Int32ub,
        "samples_per_chunk" / Int32ub,
        "sample_description_index" / Int32ub,
    )), [])
)

ChunkOffsetBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "chunk_offset" / Int32ub,
    )), [])
)

ChunkLargeOffsetBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "entries" / PrefixedArray(Int32ub, Struct(
        "chunk_offset" / Int64ub,
    ))
)

# Movie Fragment boxes, contained in moof box

MovieFragmentHeaderBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "sequence_number" / Int32ub
)

TrackFragmentBaseMediaDecodeTimeBox = Struct(
    "version" / Int8ub,
    "flags" / Const(0, Int24ub),
    "baseMediaDecodeTime" / Switch(this.version, {1: Int64ub, 0: Int32ub})
)

TrackSampleFlags = BitStruct(
    Padding(4),
    "is_leading" / Default(Enum(BitsInteger(2), UNKNOWN=0, LEADINGDEP=1, NOTLEADING=2, LEADINGNODEP=3, default=0), 0),
    "sample_depends_on" / Default(Enum(BitsInteger(2), UNKNOWN=0, DEPENDS=1, NOTDEPENDS=2, RESERVED=3, default=0), 0),
    "sample_is_depended_on" / Default(Enum(BitsInteger(2), UNKNOWN=0, NOTDISPOSABLE=1, DISPOSABLE=2, RESERVED=3, default=0), 0),
    "sample_has_redundancy" / Default(Enum(BitsInteger(2), UNKNOWN=0, REDUNDANT=1, NOTREDUNDANT=2, RESERVED=3, default=0), 0),
    "sample_padding_value" / Default(BitsInteger(3), 0),
    "sample_is_non_sync_sample" / Default(Flag, False),
    "sample_degradation_priority" / Default(BitsInteger(16), 0),
)

TrackRunBox = Struct(
    "version" / Int8ub,
    "flags" / BitStruct(
        Padding(12),
        "sample_composition_time_offsets_present" / Flag,
        "sample_flags_present" / Flag,
        "sample_size_present" / Flag,
        "sample_duration_present" / Flag,
        Padding(5),
        "first_sample_flags_present" / Flag,
        Padding(1),
        "data_offset_present" / Flag,
    ),
    "sample_count" / Int32ub,
    "data_offset" / Default(If(this.flags.data_offset_present, Int32sb), None),
    "first_sample_flags" / Default(If(this.flags.first_sample_flags_present, Int32ub), None),
    "sample_info" / Array(this.sample_count, Struct(
        "sample_duration" / If(this._.flags.sample_duration_present, Int32ub),
        "sample_size" / If(this._.flags.sample_size_present, Int32ub),
        "sample_flags" / If(this._.flags.sample_flags_present, TrackSampleFlags),
        "sample_composition_time_offsets" / If(
            this._.flags.sample_composition_time_offsets_present,
            IfThenElse(this._.version == 0, Int32ub, Int32sb)
        ),
    ))
)

TrackFragmentHeaderBox = Struct(
    "version" / Int8ub,
    "flags" / BitStruct(
        Padding(6),
        "default_base_is_moof" / Flag,
        "duration_is_empty" / Flag,
        Padding(10),
        "default_sample_flags_present" / Flag,
        "default_sample_size_present" / Flag,
        "default_sample_duration_present" / Flag,
        Padding(1),
        "sample_description_index_present" / Flag,
        "base_data_offset_present" / Flag,
    ),
    "track_ID" / Int32ub,
    "base_data_offset" / Default(If(this.flags.base_data_offset_present, Int64ub), None),
    "sample_description_index" / Default(If(this.flags.sample_description_index_present, Int32ub), None),
    "default_sample_duration" / Default(If(this.flags.default_sample_duration_present, Int32ub), None),
    "default_sample_size" / Default(If(this.flags.default_sample_size_present, Int32ub), None),
    "default_sample_flags" / Default(If(this.flags.default_sample_flags_present, TrackSampleFlags), None),
)

MovieExtendsHeaderBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Const(0, Int24ub),
    "fragment_duration" / IfThenElse(this.version == 1,
                                     Default(Int64ub, 0),
                                     Default(Int32ub, 0))
)

TrackExtendsBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "track_ID" / Int32ub,
    "default_sample_description_index" / Default(Int32ub, 1),
    "default_sample_duration" / Default(Int32ub, 0),
    "default_sample_size" / Default(Int32ub, 0),
    "default_sample_flags" / Default(TrackSampleFlags, Container()),
)

SegmentIndexBox = Struct(
    "version" / Int8ub,
    "flags" / Const(0, Int24ub),
    "reference_ID" / Int32ub,
    "timescale" / Int32ub,
    "earliest_presentation_time" / IfThenElse(this.version == 0, Int32ub, Int64ub),
    "first_offset" / IfThenElse(this.version == 0, Int32ub, Int64ub),
    Padding(2),
    "reference_count" / Int16ub,
    "references" / Array(this.reference_count, BitStruct(
        "reference_type" / Enum(BitsInteger(1), INDEX=1, MEDIA=0),
        "referenced_size" / BitsInteger(31),
        "segment_duration" / BitsInteger(32),
        "starts_with_SAP" / Flag,
        "SAP_type" / BitsInteger(3),
        "SAP_delta_time" / BitsInteger(28),
    ))
)

SampleAuxiliaryInformationSizesBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / BitStruct(
        Padding(23),
        "has_aux_info_type" / Flag,
    ),
    # Optional fields
    "aux_info_type" / Default(If(this.flags.has_aux_info_type, Int32ub), None),
    "aux_info_type_parameter" / Default(If(this.flags.has_aux_info_type, Int32ub), None),
    "default_sample_info_size" / Int8ub,
    "sample_count" / Int32ub,
    # only if sample default_sample_info_size is 0
    "sample_info_sizes" / If(this.default_sample_info_size == 0,
                             Array(this.sample_count, Int8ub))
)

SampleAuxiliaryInformationOffsetsBox = Struct(
    "version" / Int8ub,
    "flags" / BitStruct(
        Padding(23),
        "has_aux_info_type" / Flag,
    ),
    # Optional fields
    "aux_info_type" / Default(If(this.flags.has_aux_info_type, Int32ub), None),
    "aux_info_type_parameter" / Default(If(this.flags.has_aux_info_type, Int32ub), None),
    # Short offsets in version 0, long in version 1
    "offsets" / PrefixedArray(Int32ub, Switch(this.version, {0: Int32ub, 1: Int64ub}))
)

# Movie data box

MovieDataBox = Struct(
    "data" / GreedyBytes
)

# Media Info Box

SoundMediaHeaderBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / Const(0, Int24ub),
    "balance" / Default(Int16sb, 0),
    "reserved" / Const(0, Int16ub)
)


# DASH Boxes

ProtectionSystemHeaderBox = Struct(
    "version" / Rebuild(Int8ub, lambda ctx: 1 if (hasattr(ctx, "key_IDs") and ctx.key_IDs) else 0),
    "flags" / Const(0, Int24ub),
    "system_ID" / UUIDBytes(Bytes(16)),
    "key_IDs" / Default(If(this.version == 1,
                           PrefixedArray(Int32ub, UUIDBytes(Bytes(16)))),
                        None),
    "init_data" / Prefixed(Int32ub, GreedyBytes)
)

TrackEncryptionBox = Struct(
    "version" / Default(OneOf(Int8ub, (0, 1)), 0),
    "flags" / Default(Int24ub, 0),
    "_reserved" / Const(0, Int8ub),
    "default_byte_blocks" / Default(IfThenElse(
        this.version > 0,
        BitStruct(
            # count of encrypted blocks in the protection pattern, where each block is 16-bytes
            "crypt" / Nibble,
            # count of unencrypted blocks in the protection pattern
            "skip" / Nibble
        ),
        Const(0, Int8ub)
    ), 0),
    "is_encrypted" / OneOf(Int8ub, (0, 1)),
    "iv_size" / OneOf(Int8ub, (0, 8, 16)),
    "key_ID" / UUIDBytes(Bytes(16)),
    "constant_iv" / Default(If(
        this.is_encrypted and this.iv_size == 0,
        PrefixedArray(Int8ub, Byte)
    ), None)
)

SampleEncryptionBox = Struct(
    "version" / Const(0, Int8ub),
    "flags" / BitStruct(
        Padding(22),
        "has_subsample_encryption_info" / Flag,
        Padding(1)
    ),
    "sample_encryption_info" / PrefixedArray(Int32ub, Struct(
        "iv" / Bytes(8),
        # include the sub sample encryption information
        "subsample_encryption_info" / Default(If(this.flags.has_subsample_encryption_info, PrefixedArray(Int16ub, Struct(
            "clear_bytes" / Int16ub,
            "cipher_bytes" / Int32ub
        ))), None)
    ))
)

OriginalFormatBox = Struct(
    "original_format" / Default(PaddedString(4, "ascii"), "avc1")
)

SchemeTypeBox = Struct(
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "scheme_type" / Default(PaddedString(4, "ascii"), "cenc"),
    "scheme_version" / Default(Int32ub, 0x00010000),
    "schema_uri" / Default(If(this.flags & 1 == 1, CString("ascii")), None)
)

ProtectionSchemeInformationBox = Struct(
    # TODO: define which children are required 'schm', 'schi' and 'tenc'
    "children" / LazyBound(lambda _: GreedyRange(Box))
)

# PIFF boxes

UUIDBox = Struct(
    "extended_type" / UUIDBytes(Bytes(16)),
    "data" / Switch(this.extended_type, {
        UUID("A2394F52-5A9B-4F14-A244-6C427C648DF4"): SampleEncryptionBox,
        UUID("D08A4F18-10F3-4A82-B6C8-32D8ABA183D3"): ProtectionSystemHeaderBox,
        UUID("8974DBCE-7BE7-4C51-84F9-7148F9882554"): TrackEncryptionBox
    }, GreedyBytes)
)

# WebVTT boxes

CueIDBox = Struct(
    "cue_id" / GreedyString("utf8")
)

CueSettingsBox = Struct(
    "settings" / GreedyString("utf8")
)

CuePayloadBox = Struct(
    "cue_text" / GreedyString("utf8")
)

WebVTTConfigurationBox = Struct(
    "config" / GreedyString("utf8")
)

WebVTTSourceLabelBox = Struct(
    "label" / GreedyString("utf8")
)

ContainerBoxLazy = LazyBound(lambda: ContainerBox)


Box = Prefixed(Int32ub, Struct(
    "offset" / TellMinusSizeOf(Int32ub),
    "type" / PaddedString(4, "ascii"),
    "data" / Switch(this.type, {
        "ftyp": FileTypeBox,
        "styp": SegmentTypeBox,
        "mvhd": MovieHeaderBox,
        "moov": ContainerBoxLazy,
        "moof": ContainerBoxLazy,
        "mfhd": MovieFragmentHeaderBox,
        "tfdt": TrackFragmentBaseMediaDecodeTimeBox,
        "trun": TrackRunBox,
        "tfhd": TrackFragmentHeaderBox,
        "traf": ContainerBoxLazy,
        "mvex": ContainerBoxLazy,
        "mehd": MovieExtendsHeaderBox,
        "trex": TrackExtendsBox,
        "trak": ContainerBoxLazy,
        "edts": ContainerBoxLazy,
        "mdia": ContainerBoxLazy,
        "tkhd": TrackHeaderBox,
        "mdat": MovieDataBox,
        "free": FreeBox,
        "skip": SkipBox,
        "mdhd": MediaHeaderBox,
        "hdlr": HandlerReferenceBox,
        "minf": ContainerBoxLazy,
        "vmhd": VideoMediaHeaderBox,
        "dinf": ContainerBoxLazy,
        "dref": DataReferenceBox,
        "url ": DataEntryUrlBox,
        "urn ": DataEntryUrnBox,
        "stbl": ContainerBoxLazy,
        "stsd": SampleDescriptionBox,
        "stsz": SampleSizeBox,
        "stz2": SampleSizeBox2,
        "stts": TimeToSampleBox,
        "stss": SyncSampleBox,
        "ctts": CompositionOffsetBox,
        "stsc": SampleToChunkBox,
        "stco": ChunkOffsetBox,
        "co64": ChunkLargeOffsetBox,
        "smhd": SoundMediaHeaderBox,
        "sidx": SegmentIndexBox,
        "saiz": SampleAuxiliaryInformationSizesBox,
        "saio": SampleAuxiliaryInformationOffsetsBox,
        "btrt": BitRateBox,
        # dash
        "tenc": TrackEncryptionBox,
        "pssh": ProtectionSystemHeaderBox,
        "senc": SampleEncryptionBox,
        "sinf": ProtectionSchemeInformationBox,
        "frma": OriginalFormatBox,
        "schm": SchemeTypeBox,
        "schi": ContainerBoxLazy,
        # piff
        "uuid": UUIDBox,
        # HDS boxes
        "abst": HDSSegmentBox,
        "asrt": HDSSegmentRunBox,
        "afrt": HDSFragmentRunBox,
        # WebVTT
        "vttC": WebVTTConfigurationBox,
        "vlab": WebVTTSourceLabelBox,
        "vttc": ContainerBoxLazy,
        "vttx": ContainerBoxLazy,
        "iden": CueIDBox,
        "sttg": CueSettingsBox,
        "payl": CuePayloadBox
    }, default=RawBox),
    "end" / TellPlusSizeOf(Int32ub)
), includelength=True)

ContainerBox = Struct(
    "children" / GreedyRange(Box)
)

MP4 = GreedyRange(Box)
