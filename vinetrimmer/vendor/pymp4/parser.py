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
import construct.core
from construct.lib import *

log = logging.getLogger(__name__)

UNITY_MATRIX = [0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000]


class PrefixedIncludingSize(Subconstruct):
    __slots__ = ["name", "lengthfield", "subcon"]

    def __init__(self, lengthfield, subcon):
        super(PrefixedIncludingSize, self).__init__(subcon)
        self.lengthfield = lengthfield

    def _parse(self, stream, context, path):
        try:
            lengthfield_size = self.lengthfield.sizeof()
            length = self.lengthfield._parse(stream, context, path)
        except SizeofError:
            offset_start = stream.tell()
            length = self.lengthfield._parse(stream, context, path)
            lengthfield_size = stream.tell() - offset_start

        stream2 = BoundBytesIO(stream, length - lengthfield_size)
        obj = self.subcon._parse(stream2, context, path)
        return obj

    def _build(self, obj, stream, context, path):
        try:
            # needs to be both fixed size, seekable and tellable (third not checked)
            self.lengthfield.sizeof()
            if not stream.seekable:
                raise SizeofError
            offset_start = stream.tell()
            self.lengthfield._build(0, stream, context, path)
            self.subcon._build(obj, stream, context, path)
            offset_end = stream.tell()
            stream.seek(offset_start)
            self.lengthfield._build(offset_end - offset_start, stream, context, path)
            stream.seek(offset_end)
        except SizeofError:
            data = self.subcon.build(obj, context)
            sl, p_sl = 0, 0
            dlen = len(data)
            # do..while
            i = 0
            while True:
                i += 1
                p_sl = sl
                sl = len(self.lengthfield.build(dlen + sl))
                if p_sl == sl: break

                self.lengthfield._build(dlen + sl, stream, context, path)
            else:
                self.lengthfield._build(len(data), stream, context, path)
            construct.core._write_stream(stream, len(data), data)

    def _sizeof(self, context, path):
        return self.lengthfield._sizeof(context, path) + self.subcon._sizeof(context, path)


# Header box

FileTypeBox = Struct(
    "type" / Const(b"ftyp"),
    "major_brand" / String(4),
    "minor_version" / Int32ub,
    "compatible_brands" / GreedyRange(String(4)),
)

SegmentTypeBox = Struct(
    "type" / Const(b"styp"),
    "major_brand" / String(4),
    "minor_version" / Int32ub,
    "compatible_brands" / GreedyRange(String(4)),
)

# Catch find boxes

RawBox = Struct(
    "type" / String(4, padchar=b" ", paddir="right"),
    "data" / Default(GreedyBytes, b"")
)

FreeBox = Struct(
    "type" / Const(b"free"),
    "data" / GreedyBytes
)

SkipBox = Struct(
    "type" / Const(b"skip"),
    "data" / GreedyBytes
)

# Movie boxes, contained in a moov Box

MovieHeaderBox = Struct(
    "type" / Const(b"mvhd"),
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    Embedded(Switch(this.version, {
        1: Struct(
            "creation_time" / Default(Int64ub, 0),
            "modification_time" / Default(Int64ub, 0),
            "timescale" / Default(Int32ub, 10000000),
            "duration" / Int64ub
        ),
        0: Struct(
            "creation_time" / Default(Int32ub, 0),
            "modification_time" / Default(Int32ub, 0),
            "timescale" / Default(Int32ub, 10000000),
            "duration" / Int32ub,
        ),
    })),
    "rate" / Default(Int32sb, 65536),
    "volume" / Default(Int16sb, 256),
    # below could be just Padding(10) but why not
    Const(Int16ub, 0),
    Const(Int32ub, 0),
    Const(Int32ub, 0),
    "matrix" / Default(Int32sb[9], UNITY_MATRIX),
    "pre_defined" / Default(Int32ub[6], [0] * 6),
    "next_track_ID" / Default(Int32ub, 0xffffffff)
)

# Track boxes, contained in trak box

TrackHeaderBox = Struct(
    "type" / Const(b"tkhd"),
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 1),
    Embedded(Switch(this.version, {
        1: Struct(
            "creation_time" / Default(Int64ub, 0),
            "modification_time" / Default(Int64ub, 0),
            "track_ID" / Default(Int32ub, 1),
            Padding(4),
            "duration" / Default(Int64ub, 0),
        ),
        0: Struct(
            "creation_time" / Default(Int32ub, 0),
            "modification_time" / Default(Int32ub, 0),
            "track_ID" / Default(Int32ub, 1),
            Padding(4),
            "duration" / Default(Int32ub, 0),
        ),
    })),
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
    "type" / Const(b"abst"),
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "info_version" / Int32ub,
    EmbeddedBitStruct(
        Padding(1),
        "profile" / Flag,
        "live" / Flag,
        "update" / Flag,
        Padding(4)
    ),
    "time_scale" / Int32ub,
    "current_media_time" / Int64ub,
    "smpte_time_code_offset" / Int64ub,
    "movie_identifier" / CString(),
    "server_entry_table" / PrefixedArray(Int8ub, CString()),
    "quality_entry_table" / PrefixedArray(Int8ub, CString()),
    "drm_data" / CString(),
    "metadata" / CString(),
    "segment_run_table" / PrefixedArray(Int8ub, LazyBound(lambda x: Box)),
    "fragment_run_table" / PrefixedArray(Int8ub, LazyBound(lambda x: Box))
)

HDSSegmentRunBox = Struct(
    "type" / Const(b"asrt"),
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "quality_entry_table" / PrefixedArray(Int8ub, CString()),
    "segment_run_enteries" / PrefixedArray(Int32ub, Struct(
        "first_segment" / Int32ub,
        "fragments_per_segment" / Int32ub
    ))
)

HDSFragmentRunBox = Struct(
    "type" / Const(b"afrt"),
    "version" / Default(Int8ub, 0),
    "flags" / BitStruct(
        Padding(23),
        "update" / Flag
    ),
    "time_scale" / Int32ub,
    "quality_entry_table" / PrefixedArray(Int8ub, CString()),
    "fragment_run_enteries" / PrefixedArray(Int32ub, Struct(
        "first_fragment" / Int32ub,
        "first_fragment_timestamp" / Int64ub,
        "fragment_duration" / Int32ub,
        "discontinuity" / If(this.fragment_duration == 0, Int8ub)
    ))
)


# Boxes contained by Media Box

class ISO6392TLanguageCode(Adapter):
    def _decode(self, obj, context):
        """
        Get the python representation of the obj
        """
        return b''.join(map(int2byte, [c + 0x60 for c in bytearray(obj)])).decode("utf8")

    def _encode(self, obj, context):
        """
        Get the bytes representation of the obj
        """
        return [c - 0x60 for c in bytearray(obj.encode("utf8"))]


MediaHeaderBox = Struct(
    "type" / Const(b"mdhd"),
    "version" / Default(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "creation_time" / IfThenElse(this.version == 1, Int64ub, Int32ub),
    "modification_time" / IfThenElse(this.version == 1, Int64ub, Int32ub),
    "timescale" / Int32ub,
    "duration" / IfThenElse(this.version == 1, Int64ub, Int32ub),
    Embedded(BitStruct(
        Padding(1),
        "language" / ISO6392TLanguageCode(BitsInteger(5)[3]),
    )),
    Padding(2, pattern=b"\x00"),
)

HandlerReferenceBox = Struct(
    "type" / Const(b"hdlr"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    Padding(4, pattern=b"\x00"),
    "handler_type" / String(4),
    Padding(12, pattern=b"\x00"),  # Int32ub[3]
    "name" / CString(encoding="utf8")
)

# Boxes contained by Media Info Box

VideoMediaHeaderBox = Struct(
    "type" / Const(b"vmhd"),
    "version" / Default(Int8ub, 0),
    "flags" / Const(Int24ub, 1),
    "graphics_mode" / Default(Int16ub, 0),
    "opcolor" / Struct(
        "red" / Default(Int16ub, 0),
        "green" / Default(Int16ub, 0),
        "blue" / Default(Int16ub, 0),
    ),
)

DataEntryUrlBox = PrefixedIncludingSize(Int32ub, Struct(
    "type" / Const(b"url "),
    "version" / Const(Int8ub, 0),
    "flags" / BitStruct(
        Padding(23), "self_contained" / Rebuild(Flag, ~this._.location)
    ),
    "location" / If(~this.flags.self_contained, CString(encoding="utf8")),
))

DataEntryUrnBox = PrefixedIncludingSize(Int32ub, Struct(
    "type" / Const(b"urn "),
    "version" / Const(Int8ub, 0),
    "flags" / BitStruct(
        Padding(23), "self_contained" / Rebuild(Flag, ~(this._.name & this._.location))
    ),
    "name" / If(this.flags == 0, CString(encoding="utf8")),
    "location" / If(this.flags == 0, CString(encoding="utf8")),
))

DataReferenceBox = Struct(
    "type" / Const(b"dref"),
    "version" / Const(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "data_entries" / PrefixedArray(Int32ub, Select(DataEntryUrnBox, DataEntryUrlBox)),
)

# Sample Table boxes (stbl)

MP4ASampleEntryBox = Struct(
    "version" / Default(Int16ub, 0),
    "revision" / Const(Int16ub, 0),
    "vendor" / Const(Int32ub, 0),
    "channels" / Default(Int16ub, 2),
    "bits_per_sample" / Default(Int16ub, 16),
    "compression_id" / Default(Int16sb, 0),
    "packet_size" / Const(Int16ub, 0),
    "sampling_rate" / Int16ub,
    Padding(2)
)


class MaskedInteger(Adapter):
    def _decode(self, obj, context):
        return obj & 0x1F

    def _encode(self, obj, context):
        return obj & 0x1F


AAVC = Struct(
    "version" / Const(Int8ub, 1),
    "profile" / Int8ub,
    "compatibility" / Int8ub,
    "level" / Int8ub,
    EmbeddedBitStruct(
        Padding(6, pattern=b'\x01'),
        "nal_unit_length_field" / Default(BitsInteger(2), 3),
    ),
    "sps" / Default(PrefixedArray(MaskedInteger(Int8ub), PascalString(Int16ub)), []),
    "pps" / Default(PrefixedArray(Int8ub, PascalString(Int16ub)), [])
)

HVCC = Struct(
    EmbeddedBitStruct(
        "version" / Const(BitsInteger(8), 1),
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
    "revision" / Const(Int16ub, 0),
    "vendor" / Default(String(4, padchar=b" "), b"brdy"),
    "temporal_quality" / Default(Int32ub, 0),
    "spatial_quality" / Default(Int32ub, 0),
    "width" / Int16ub,
    "height" / Int16ub,
    "horizontal_resolution" / Default(Int16ub, 72),  # TODO: actually a fixed point decimal
    Padding(2),
    "vertical_resolution" / Default(Int16ub, 72),  # TODO: actually a fixed point decimal
    Padding(2),
    "data_size" / Const(Int32ub, 0),
    "frame_count" / Default(Int16ub, 1),
    "compressor_name" / Default(String(32, padchar=b" "), ""),
    "depth" / Default(Int16ub, 24),
    "color_table_id" / Default(Int16sb, -1),
    "avc_data" / PrefixedIncludingSize(Int32ub, Struct(
    "type" / String(4, padchar=b" ", paddir="right"),
        Embedded(Switch(this.type, {
            b"avcC": AAVC,
            b"hvcC": HVCC,
        }, Struct("data" / GreedyBytes)))
    )),
    "sample_info" / LazyBound(lambda _: GreedyRange(Box))
)

SampleEntryBox = PrefixedIncludingSize(Int32ub, Struct(
    "format" / String(4, padchar=b" ", paddir="right"),
    Padding(6, pattern=b"\x00"),
    "data_reference_index" / Default(Int16ub, 1),
    Embedded(Switch(this.format, {
        b"ec-3": MP4ASampleEntryBox,
        b"mp4a": MP4ASampleEntryBox,
        b"enca": MP4ASampleEntryBox,
        b"avc1": AVC1SampleEntryBox,
        b"encv": AVC1SampleEntryBox,
        b"wvtt": Struct("children" / LazyBound(lambda ctx: GreedyRange(Box)))
    }, Struct("data" / GreedyBytes)))
))

BitRateBox = Struct(
    "type" / Const(b"btrt"),
    "bufferSizeDB" / Int32ub,
    "maxBitrate" / Int32ub,
    "avgBirate" / Int32ub,
)

SampleDescriptionBox = Struct(
    "type" / Const(b"stsd"),
    "version" / Default(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "entries" / PrefixedArray(Int32ub, SampleEntryBox)
)

SampleSizeBox = Struct(
    "type" / Const(b"stsz"),
    "version" / Int8ub,
    "flags" / Const(Int24ub, 0),
    "sample_size" / Int32ub,
    "sample_count" / Int32ub,
    "entry_sizes" / If(this.sample_size == 0, Array(this.sample_count, Int32ub))
)

SampleSizeBox2 = Struct(
    "type" / Const(b"stz2"),
    "version" / Int8ub,
    "flags" / Const(Int24ub, 0),
    Padding(3, pattern=b"\x00"),
    "field_size" / Int8ub,
    "sample_count" / Int24ub,
    "entries" / Array(this.sample_count, Struct(
        "entry_size" / LazyBound(lambda ctx: globals()["Int%dub" % ctx.field_size])
    ))
)

SampleDegradationPriorityBox = Struct(
    "type" / Const(b"stdp"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
)

TimeToSampleBox = Struct(
    "type" / Const(b"stts"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "sample_count" / Int32ub,
        "sample_delta" / Int32ub,
    )), [])
)

SyncSampleBox = Struct(
    "type" / Const(b"stss"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "sample_number" / Int32ub,
    )), [])
)

SampleToChunkBox = Struct(
    "type" / Const(b"stsc"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "first_chunk" / Int32ub,
        "samples_per_chunk" / Int32ub,
        "sample_description_index" / Int32ub,
    )), [])
)

ChunkOffsetBox = Struct(
    "type" / Const(b"stco"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "entries" / Default(PrefixedArray(Int32ub, Struct(
        "chunk_offset" / Int32ub,
    )), [])
)

ChunkLargeOffsetBox = Struct(
    "type" / Const(b"co64"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "entries" / PrefixedArray(Int32ub, Struct(
        "chunk_offset" / Int64ub,
    ))
)

# Movie Fragment boxes, contained in moof box

MovieFragmentHeaderBox = Struct(
    "type" / Const(b"mfhd"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "sequence_number" / Int32ub
)

TrackFragmentBaseMediaDecodeTimeBox = Struct(
    "type" / Const(b"tfdt"),
    "version" / Int8ub,
    "flags" / Const(Int24ub, 0),
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
    "type" / Const(b"trun"),
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
    "type" / Const(b"tfhd"),
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
    "type" / Const(b"mehd"),
    "version" / Default(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "fragment_duration" / IfThenElse(this.version == 1,
                                     Default(Int64ub, 0),
                                     Default(Int32ub, 0))
)

TrackExtendsBox = Struct(
    "type" / Const(b"trex"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "track_ID" / Int32ub,
    "default_sample_description_index" / Default(Int32ub, 1),
    "default_sample_duration" / Default(Int32ub, 0),
    "default_sample_size" / Default(Int32ub, 0),
    "default_sample_flags" / Default(TrackSampleFlags, Container()),
)

SegmentIndexBox = Struct(
    "type" / Const(b"sidx"),
    "version" / Int8ub,
    "flags" / Const(Int24ub, 0),
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
    "type" / Const(b"saiz"),
    "version" / Const(Int8ub, 0),
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
    "type" / Const(b"saio"),
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
    "type" / Const(b"mdat"),
    "data" / GreedyBytes
)

# Media Info Box

SoundMediaHeaderBox = Struct(
    "type" / Const(b"smhd"),
    "version" / Const(Int8ub, 0),
    "flags" / Const(Int24ub, 0),
    "balance" / Default(Int16sb, 0),
    "reserved" / Const(Int16ub, 0)
)


# DASH Boxes

class UUIDBytes(Adapter):
    def _decode(self, obj, context):
        return UUID(bytes=obj)

    def _encode(self, obj, context):
        return obj.bytes


ProtectionSystemHeaderBox = Struct(
    "type" / If(this._.type != b"uuid", Const(b"pssh")),
    "version" / Rebuild(Int8ub, lambda ctx: 1 if (hasattr(ctx, "key_IDs") and ctx.key_IDs) else 0),
    "flags" / Const(Int24ub, 0),
    "system_ID" / UUIDBytes(Bytes(16)),
    "key_IDs" / Default(If(this.version == 1,
                           PrefixedArray(Int32ub, UUIDBytes(Bytes(16)))),
                        None),
    "init_data" / Prefixed(Int32ub, GreedyBytes)
)

TrackEncryptionBox = Struct(
    "type" / If(this._.type != b"uuid", Const(b"tenc")),
    "version" / Default(OneOf(Int8ub, (0, 1)), 0),
    "flags" / Default(Int24ub, 0),
    "_reserved" / Const(Int8ub, 0),
    "default_byte_blocks" / Default(IfThenElse(
        this.version > 0,
        BitStruct(
            # count of encrypted blocks in the protection pattern, where each block is 16-bytes
            "crypt" / Nibble,
            # count of unencrypted blocks in the protection pattern
            "skip" / Nibble
        ),
        Const(Int8ub, 0)
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
    "type" / If(this._.type != b"uuid", Const(b"senc")),
    "version" / Const(Int8ub, 0),
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
    "type" / Const(b"frma"),
    "original_format" / Default(String(4), b"avc1")
)

SchemeTypeBox = Struct(
    "type" / Const(b"schm"),
    "version" / Default(Int8ub, 0),
    "flags" / Default(Int24ub, 0),
    "scheme_type" / Default(String(4), b"cenc"),
    "scheme_version" / Default(Int32ub, 0x00010000),
    "schema_uri" / Default(If(this.flags & 1 == 1, CString()), None)
)

ProtectionSchemeInformationBox = Struct(
    "type" / Const(b"sinf"),
    # TODO: define which children are required 'schm', 'schi' and 'tenc'
    "children" / LazyBound(lambda _: GreedyRange(Box))
)

# PIFF boxes

UUIDBox = Struct(
    "type" / Const(b"uuid"),
    "extended_type" / UUIDBytes(Bytes(16)),
    "data" / Switch(this.extended_type, {
        UUID("A2394F52-5A9B-4F14-A244-6C427C648DF4"): SampleEncryptionBox,
        UUID("D08A4F18-10F3-4A82-B6C8-32D8ABA183D3"): ProtectionSystemHeaderBox,
        UUID("8974DBCE-7BE7-4C51-84F9-7148F9882554"): TrackEncryptionBox
    }, GreedyBytes)
)

# WebVTT boxes

CueIDBox = Struct(
    "type" / Const(b"iden"),
    "cue_id" / GreedyString("utf8")
)

CueSettingsBox = Struct(
    "type" / Const(b"sttg"),
    "settings" / GreedyString("utf8")
)

CuePayloadBox = Struct(
    "type" / Const(b"payl"),
    "cue_text" / GreedyString("utf8")
)

WebVTTConfigurationBox = Struct(
    "type" / Const(b"vttC"),
    "config" / GreedyString("utf8")
)

WebVTTSourceLabelBox = Struct(
    "type" / Const(b"vlab"),
    "label" / GreedyString("utf8")
)

ContainerBoxLazy = LazyBound(lambda ctx: ContainerBox)


class TellMinusSizeOf(Subconstruct):
    def __init__(self, subcon):
        super(TellMinusSizeOf, self).__init__(subcon)
        self.flagbuildnone = True

    def _parse(self, stream, context, path):
        return stream.tell() - self.subcon.sizeof(context)

    def _build(self, obj, stream, context, path):
        return b""

    def sizeof(self, context=None, **kw):
        return 0


Box = PrefixedIncludingSize(Int32ub, Struct(
    "offset" / TellMinusSizeOf(Int32ub),
    "type" / Peek(String(4, padchar=b" ", paddir="right")),
    Embedded(Switch(this.type, {
        b"ftyp": FileTypeBox,
        b"styp": SegmentTypeBox,
        b"mvhd": MovieHeaderBox,
        b"moov": ContainerBoxLazy,
        b"moof": ContainerBoxLazy,
        b"mfhd": MovieFragmentHeaderBox,
        b"tfdt": TrackFragmentBaseMediaDecodeTimeBox,
        b"trun": TrackRunBox,
        b"tfhd": TrackFragmentHeaderBox,
        b"traf": ContainerBoxLazy,
        b"mvex": ContainerBoxLazy,
        b"mehd": MovieExtendsHeaderBox,
        b"trex": TrackExtendsBox,
        b"trak": ContainerBoxLazy,
        b"mdia": ContainerBoxLazy,
        b"tkhd": TrackHeaderBox,
        b"mdat": MovieDataBox,
        b"free": FreeBox,
        b"skip": SkipBox,
        b"mdhd": MediaHeaderBox,
        b"hdlr": HandlerReferenceBox,
        b"minf": ContainerBoxLazy,
        b"vmhd": VideoMediaHeaderBox,
        b"dinf": ContainerBoxLazy,
        b"dref": DataReferenceBox,
        b"stbl": ContainerBoxLazy,
        b"stsd": SampleDescriptionBox,
        b"stsz": SampleSizeBox,
        b"stz2": SampleSizeBox2,
        b"stts": TimeToSampleBox,
        b"stss": SyncSampleBox,
        b"stsc": SampleToChunkBox,
        b"stco": ChunkOffsetBox,
        b"co64": ChunkLargeOffsetBox,
        b"smhd": SoundMediaHeaderBox,
        b"sidx": SegmentIndexBox,
        b"saiz": SampleAuxiliaryInformationSizesBox,
        b"saio": SampleAuxiliaryInformationOffsetsBox,
        b"btrt": BitRateBox,
        # dash
        b"tenc": TrackEncryptionBox,
        b"pssh": ProtectionSystemHeaderBox,
        b"senc": SampleEncryptionBox,
        b"sinf": ProtectionSchemeInformationBox,
        b"frma": OriginalFormatBox,
        b"schm": SchemeTypeBox,
        b"schi": ContainerBoxLazy,
        # piff
        b"uuid": UUIDBox,
        # HDS boxes
        b'abst': HDSSegmentBox,
        b'asrt': HDSSegmentRunBox,
        b'afrt': HDSFragmentRunBox,
        # WebVTT
        b"vttC": WebVTTConfigurationBox,
        b"vlab": WebVTTSourceLabelBox,
        b"vttc": ContainerBoxLazy,
        b"vttx": ContainerBoxLazy,
        b"iden": CueIDBox,
        b"sttg": CueSettingsBox,
        b"payl": CuePayloadBox
    }, default=RawBox)),
    "end" / Tell
))

ContainerBox = Struct(
    "type" / String(4, padchar=b" ", paddir="right"),
    "children" / GreedyRange(Box)
)

MP4 = GreedyRange(Box)
