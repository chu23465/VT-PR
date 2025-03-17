# encoding: utf-8
#
#  --------------------------------------------
#  based on https://github.com/yuppity/ttml2srt
#  --------------------------------------------
# SPDX-License-Identifier: LGPL-2.1-or-later

from __future__ import unicode_literals, absolute_import, division

import re
import io
import os.path
import json
from collections import OrderedDict
from copy import deepcopy
import tempfile

try:
    from defusedxml import minidom  # type: ignore
except:
    from xml.dom import minidom


class TimestampConverter(object):

    def __init__(self, frame_rate=23.976, tick_rate=1):
        self.tick_rate = tick_rate
        self.frame_rate = frame_rate

    def timeexpr_to_ms(self, *args):
        return self._timeexpr_to_ms(*args)

    def _timeexpr_to_ms(self, time_expr):
        """Use the given time expression to get a matching conversion method
        to overwrite self.timeexpr_to_ms() with.
        """

        self.timeexpr_to_ms = self.determine_ms_convfn(time_expr)
        return self.timeexpr_to_ms(time_expr)

    def _hhmmss_to_ms(self, hh, mm, ss):
        return hh * 3600 * 1000 + mm * 60 * 1000 + ss * 1000

    def subrip_to_ms(self, timestamp):
        """Desconstruct SubRip timecode down to milliseconds
        """

        hh, mm, ss, ms = re.split(r'[:,]', timestamp)
        return int(int(hh) * 3.6e6 + int(mm) * 60000 + int(ss) * 1000 + int(ms))

    def _metric_to_ms(self, metric_multiplier, metric_value):
        return int(metric_multiplier * metric_value)

    def _ms_to_hhmmssms(self, ms):
        hh = int(ms / 3.6e6)
        mm = int((ms % 3.6e6) / 60000)
        ss = int((ms % 60000) / 1000)
        ms = int(ms % 1000)

        return hh, mm, ss, ms

    def ms_to_subrip(self, ms):
        """Build SubRip timecode from milliseconds
        """

        hh, mm, ss, ms = self._ms_to_hhmmssms(ms)
        return '{:02d}:{:02d}:{:02d},{:03d}'.format(hh, mm, ss, ms)

    def ms_to_ssa(self, ms):
        """Build SSA/ASS timecode from milliseconds
        """

        hh, mm, ss, ms = self._ms_to_hhmmssms(ms)
        return '{:01d}:{:02d}:{:02d}.{:02d}'.format(hh, mm, ss, int(ms / 10))

    def frames_to_ms(self, frames):
        """Convert frame count to ms
        """

        return int(int(frames) * (1000 / self.frame_rate))

    def offset_frames_to_ms(self, time):
        """Convert offset-time expression with f metric to milliseconds.
        """

        frames = float(time[:-1])
        return int(int(frames) * (1000 / self.frame_rate))

    def offset_ticks_to_ms(self, time):
        """Convert offset-time expression with t metric to milliseconds.
        """

        ticks = int(time[:-1])
        seconds = 1.0 / self.tick_rate
        return (seconds * ticks) * 1000

    def offset_hours_to_ms(self, time):
        """Convert offset-time expression with h metric to milliseconds.
        """

        hours = float(time[:-1])
        return self._metric_to_ms(3.6e6, hours)

    def offset_minutes_to_ms(self, time):
        """Convert offset-time expression with m metric to milliseconds.
        """

        return self._metric_to_ms(60 * 1000, float(time[:-1]))

    def offset_seconds_to_ms(self, time):
        """Convert offset-time expression with s metric to milliseconds.
        """

        seconds = float(time[:-1])
        return self._metric_to_ms(1000, seconds)

    def offset_ms_to_ms(self, time):
        """Convert offset-time expression with ms metric to milliseconds.
        """

        ms = int(time[:-2])
        return ms

    def fraction_timestamp_to_ms(self, timestamp):
        """Convert hh:mm:ss.fraction to milliseconds
        """

        hh, mm, ss, fraction = re.split(r'[:.]', timestamp)
        hh, mm, ss = [int(i) for i in (hh, mm, ss)]
        # Resolution beyond ms is useless for our purposes
        ms = int(fraction[:3])

        return self._hhmmss_to_ms(hh, mm, ss) + ms

    def frame_timestamp_to_ms(self, timestamp):
        """Convert hh:mm:ss:frames to milliseconds

        Will handle hh:mm:ss:frames.sub-frames by discarding the sub-frame part
        """

        hh, mm, ss, frames = [int(i) for i in timestamp.split('.')[0].split(':')]
        hhmmss_ms = self._hhmmss_to_ms(hh, mm, ss)
        ms = self.frames_to_ms(frames)
        return hhmmss_ms + ms

    def determine_ms_convfn(self, time_expr):
        """Determine approriate ms conversion fn to pass the time expression to.

        Args:
            time_exrp (str): TTML time expression

        Return:
            Conversion method (callable)

        Strips the time expression of digits and uses the resulting string as
        a key to a dict of conversion methods.
        """

        # Map time expression delimiters to conversion methods. Saves
        # us from having to exec multibranch code on each line but assumes all
        # time expressions to be of the same form.
        time_expr_fns = {

            # clock-time, no frames or fraction
            # Example(s): "00:02:23"
            '::': self.frame_timestamp_to_ms,

            # clock-time, frames
            # Example(s): "00:02:23:12", "00:02:23:12.222"
            ':::': self.frame_timestamp_to_ms,
            ':::.': self.frame_timestamp_to_ms,

            # clock-time, fraction
            # Example(s): "00:02:23.283"
            '::.': self.fraction_timestamp_to_ms,

            # offset-time, hour metric
            # Example(s): "1h", "1.232837372637h"
            'h': self.offset_hours_to_ms,
            '.h': self.offset_hours_to_ms,

            # offset-time, minute metric
            # Example(s): "1m", "13.72986323m"
            'm': self.offset_minutes_to_ms,
            '.m': self.offset_minutes_to_ms,

            # offset-time, second metric
            # Example(s): "1s", "113.2312312s"
            's': self.offset_seconds_to_ms,
            '.s': self.offset_seconds_to_ms,

            # offset-time, millisecond metric
            # Example(s): "1ms", "1000.1231231231223ms"
            'ms': self.offset_ms_to_ms,
            '.ms': self.offset_ms_to_ms,

            # offset-time, frame metric
            # Example(s): "100f"
            'f': self.offset_frames_to_ms,
            '.f': self.offset_frames_to_ms,

            # offset-time, tick metric
            # Example(s): "19298323t"
            't': self.offset_ticks_to_ms,
            '.t': self.offset_ticks_to_ms,

        }

        try:
            delims = ''.join([i for i in time_expr if not i.isdigit()])
            return time_expr_fns[delims]
        except KeyError:
            raise NotImplementedError(
                'Unknown timestamp format ("{}")'.format(time_expr))


class Ttml2Ssa(object):

    VERSION = '0.3.8'

    TIME_BASES = [
        'media',
        'smpte',
    ]

    SCALE = {
        'NTSC2PAL' : 23.976/25,
        'PAL2NTSC' : 25/23.976,
        'NTSC2FILM' : 23.976/24,
        'PAL2FILM' : 25/24,
        'FILM2NTSC' : 24/23.976,
        'FILM2PAL' : 24/25
    }

    TOP_MARKER = '{\\an8}'

    def __init__(self, shift=0, source_fps=23.976, scale_factor=1, subtitle_language=None):
        self.shift = shift
        self.source_fps = source_fps
        self.subtitle_language = subtitle_language
        self.scale_factor = scale_factor
        self.ssa_timestamp_min_sep = 200
        self.use_cosmetic_filter = True
        self.use_language_filter = True
        self.fix_amazon_errors = True

        self.allow_italics = True
        self.allow_top_pos = True

        self.allow_timestamp_manipulation = True
        self.fix_timestamp_collisions = True
        self.fix_duplicated_entries = True

        try:
            self.cache_directory = tempfile.gettempdir() # Fails on Android
            self.cache_downloaded_subtitles = True
        except:
            self.cache_directory = None
            self.cache_downloaded_subtitles = False

        self._styles = {}
        self._italic_style_ids = []
        self._top_regions_ids = []

        self._allowed_style_attrs = (
            'color',
            'fontStyle',
            'fontWeight',
        )

        ## This variable stores the language ID from the xml file.
        #  But it may not exist or it may be wrong.
        self.lang = None

        self.ssa_style = OrderedDict([
            ('Fontname', 'Arial'),
            ('Fontsize', 50),
            ('PrimaryColour', '&H00EEEEEE'),
            ('SecondaryColour', '&H000000FF'),
            ('BackColour', '&H40000000'),
            ('OutlineColour', '&H00000000'),
            ('Bold', 0),
            ('Italic', 0),
            ('Underline', 0),
            ('Alignment', 2),
            ('BorderStyle', 1),
            ('Outline', 2),
            ('Shadow', 3),
            ('MarginL', 0),
            ('MarginR', 0),
            ('MarginV', 40),
            ('StrikeOut', 0),
            ('ScaleX', 100),
            ('ScaleY', 100),
            ('Spacing', 0),
            ('Angle', 0),
            ('Encoding', 1)
        ])
        self.ssa_playresx = 1280
        self.ssa_playresy = 720

        self.entries = []

    def set_video_aspect_ratio(self, ratio):
        """ Adjust the SSA options PlaResX and PlayRexY according to the aspect ratio of the video """
        self.ssa_playresy = int(self.ssa_playresx / ratio)

    def parse_subtitle_file(self, filename, file_encoding=None):
        """Read and parse a subtitle file.
        If the file has the vtt or srt extension it will be parsed as a vtt. Otherwise it will be parsed as ttml.
        The result is stored in the `entries` list, as begin (ms), end (ms), text, position.
        """

        extension = os.path.splitext(filename)[1].lower()
        if extension == ".srt" or extension == ".vtt":
            self.parse_vtt_file(filename, file_encoding)
        else:
            self.parse_ttml_file(filename, file_encoding)

    def parse_ttml_file(self, filename, file_encoding=None):
        """Read and parse a ttml/xml/dfxp file.
        The result is stored in the `entries` list, as begin (ms), end (ms), text, position.
        """

        doc = self._read_file(filename, file_encoding)
        self.parse_ttml_from_string(doc.encode('utf-8'))

    def parse_ttml_from_string(self, doc):
        """Read and parse a ttml/xml/dfxp subtitle from a string.
        The result is stored in the `entries` list, as begin (ms), end (ms), text, position.
        """

        def extract_rate(s):
            try:
                m = s.split(' ')
                return int(m[0]) / int(m[1])
            except:
                return 1

        del self.entries [:]
        self._tc = TimestampConverter()

        ttml_dom = minidom.parseString(doc)
        self._encoding = ttml_dom.encoding

        if self._encoding and self._encoding.lower() not in ['utf8', 'utf-8']:
            # Don't bother with subtitles that aren't utf-8 encoded
            # but assume utf-8 when the encoding attr is missing
            raise NotImplementedError('Source is not utf-8 encoded')

        # Get the root tt element (assume the file contains
        # a single subtitle document)
        tt_element = ttml_dom.getElementsByTagNameNS('*', 'tt')[0]

        # Extract doc language
        # https://tools.ietf.org/html/rfc4646#section-2.1
        language_tag = tt_element.getAttribute('xml:lang') or ''
        self.lang = re.split(r'\s+', language_tag.strip())[0].split('-')[0]

        # Store TT parameters as instance vars (in camel case)
        opttime = {}
        for ttp_name, defval, convfn in (
                # (tt param, default val, fn to process the str)
                ('frameRate', 0, lambda x: float(x)),
                ('tickRate', 0, lambda x: int(x)),
                ('timeBase', 'media', lambda x: x),
                ('clockMode', '', lambda x: x),
                #('frameRateMultiplier', 1, lambda x: int(x)),
                ('frameRateMultiplier', 1, lambda x: extract_rate(x)),
                ('subFrameRate', 1, lambda x: int(x)),
                ('markerMode', '', lambda x: x),
                ('dropMode', '', lambda x: x),
        ):
            ttp_val = getattr(
                tt_element.attributes.get('ttp:' + ttp_name), 'value', defval)
            opttime[Ttml2Ssa._snake_to_camel(ttp_name)] = convfn(ttp_val)

        if opttime['time_base'] not in Ttml2Ssa.TIME_BASES:
            raise NotImplementedError('No support for "{}" time base'.format(
                opttime['time_base']))

        # Set effective tick rate as per
        # https://www.w3.org/TR/ttml1/#parameter-attribute-tickRate
        # This will obviously only be made use of if we encounter offset-time
        # expressions that have the tick metric.
        self._tc.tick_rate = opttime['tick_rate']
        if not opttime['tick_rate'] and opttime['frame_rate']:
            self._tc.tick_rate = int(opttime['frame_rate'] * opttime['sub_frame_rate'])
        elif not opttime['tick_rate']:
            self._tc.tick_rate = 1

        # Set FPS to source_fps if no TT param
        self._tc.frame_rate = opttime['frame_rate'] or self.source_fps

        # Grab <style>s
        # https://www.w3.org/TR/ttml1/#styling-attribute-vocabulary
        for styles_container in ttml_dom.getElementsByTagName('styling'):
            for style in styles_container.getElementsByTagName('style'):
                style_id = getattr(
                    style.attributes.get('xml:id', {}), 'value', None)
                if not style_id:
                    continue
                self._styles[style_id] = self._get_tt_style_attrs(style, True)
                if self._styles[style_id]['font_style'] == 'italic':
                    self._italic_style_ids.append(style_id)

        # Grab top regions
        for layout_container in ttml_dom.getElementsByTagName('layout'):
            for region in layout_container.getElementsByTagName('region'):
                region_id = getattr(
                    region.attributes.get('xml:id', {}), 'value', None)
                if region_id:
                    # Case 1: displayAlign is in layout -> region
                    if region.getAttribute('tts:displayAlign') == 'before':
                        self._top_regions_ids.append(region_id)
                    # Case 2: displayAlign is in layout -> region -> style
                    for style in region.getElementsByTagName('style'):
                        if style.getAttribute('tts:displayAlign') == 'before':
                            self._top_regions_ids.append(region_id)

        # Get em <p>s.
        #
        # CAUTION: This is very naive and will fail us when the TTML
        # document contains multiple local time contexts with their own
        # offsets, or even just a single context with an offset other
        # than zero.
        lines = [i for i in ttml_dom.getElementsByTagNameNS('*', 'p') \
            if 'begin' in i.attributes.keys()]

        for p in lines:
            entry = {}
            ms_begin, ms_end, text, position = self._process_parag(p)
            entry['ms_begin'] = ms_begin
            entry['ms_end'] = ms_end
            entry['text'] = text
            entry['position'] = position
            self.entries.append(entry)

        self._apply_options()

    def _apply_options(self):
        if self.scale_factor != 1:
            self._scale_timestamps(self.scale_factor)

        if self.shift:
            self._shift_timestamps(self.shift)

        if self.fix_duplicated_entries:
            self.entries = self._remove_duplicated(self.entries)

        # Sort and fix timestamps
        self.entries = sorted(self.entries, key=lambda x: x['ms_begin'])
        if self.allow_timestamp_manipulation and self.fix_timestamp_collisions:
            self.entries = self._sequalize(self.entries)

        if self.use_cosmetic_filter:
            self._cosmetic_filter()

        if self.use_language_filter:
            self._language_fix_filter()

    def _get_tt_style_attrs(self, node, in_head=False):
        """Extract node's style attributes

        Node can be a style definition element or a content element (<p>).

        Attributes are filtered against :attr:`Ttml2Ssa._allowed_style_attrs`
        and returned as a dict whose keys are attribute names camel cased.
        """

        style = {}
        for attr_name in self._allowed_style_attrs:
            tts = 'tts:' + attr_name
            attr_name = Ttml2Ssa._snake_to_camel(attr_name)
            style[attr_name] = node.getAttribute(tts) or ''
        if not in_head:
            style['style_id'] = node.getAttribute('style')
        return style


    def _extract_dialogue(self, nodes, styles=[]):
        """Extract text content and styling attributes from <p> elements.

        Args:
            nodes (xml.dom.minidom.Node): List of <p> elements
            styles (list): List of style signifiers that should be
                applied to each node

        Return:
            List of SRT paragraphs (strings)
        """

        dialogue = []

        for node in nodes:
            _styles = []

            if node.nodeType == node.TEXT_NODE:
                format_str = '{}'

                # Take the liberty to make a few stylistic choices. We don't
                # want too many leading spaces or any unnecessary new lines
                text = re.sub(r'^\s{4,}', '', node.nodeValue.replace('\n', ''))

                for style in styles:
                    format_str = '{ot}{f}{et}'.format(
                        et='</{}>'.format(style),
                        ot='<{}>'.format(style),
                        f=format_str)

                dialogue.append(format_str.format(text))

            elif node.localName == 'br':
                dialogue.append('\n')

            # Checks for italics for now but shouldn't be too much work to
            # support bold text or colors
            elif node.localName == 'span':
                style_attrs = self._get_tt_style_attrs(node)
                inline_italic = style_attrs['font_style'] == 'italic'
                assoc_italic = style_attrs['style_id'] in self._italic_style_ids
                if inline_italic or assoc_italic or node.parentNode.getAttribute('style') == 'AmazonDefaultStyle':
                    _styles.append('i')

            if node.hasChildNodes():
                dialogue += self._extract_dialogue(node.childNodes, _styles)

        return ''.join(dialogue)

    def _process_parag(self, paragraph):
        """Extract begin and end attrs, and text content of <p> element.

        Args:
            paragragh (xml.dom.minidom.Element): <p> element.

        Returns:
            Tuple containing
                begin in ms,
                end in ms,
                text content in Subrip (SRT) format,
                position (top or bottom) where the text should appear
        """

        begin = paragraph.attributes['begin'].value
        end = paragraph.attributes['end'].value

        ms_begin = self._tc.timeexpr_to_ms(begin)
        ms_end = self._tc.timeexpr_to_ms(end)

        dialogue = self._extract_dialogue(paragraph.childNodes)

        # Trim lines and remove empty lines
        new_text = ""
        for line in dialogue.splitlines():
            line = line.strip()
            if line:
                if new_text: new_text += "\n"
                new_text += line
        dialogue = new_text

        position = 'top' if paragraph.getAttribute('region') in self._top_regions_ids else 'bottom'

        return ms_begin, ms_end, dialogue, position


    def parse_vtt_file(self, filename, file_encoding=None):
        """Read and parse a vtt/srt file.
        The result is stored in the `entries` list, as begin (ms), end (ms), text, position.
        """

        vtt = self._read_file(filename, file_encoding)
        self.parse_vtt_from_string(vtt)

    def parse_vtt_from_string(self, vtt):
        """Read and parse a vtt/srt subtitle from a string.
        The result is stored in the `entries` list, as begin (ms), end (ms), text, position.
        """

        def unescape_text(text):
            try:
                # Python 2
                from HTMLParser import HTMLParser
                htmlparser = HTMLParser()
            except ImportError:
                # Python 3
                import html
                htmlparser = html
            no_escape_list = [('&lrm;', '<lrm>'), ('&rlm;', '<rlm>')]
            for c in no_escape_list:
                text = text.replace(c[0], c[1])
            text = htmlparser.unescape(text)
            for c in no_escape_list:
                text = text.replace(c[1], c[0])
            return text

        del self.entries [:]
        self._tc = TimestampConverter()

        lines = vtt.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            #m = re.match(r'(?P<t1>\d{2}:\d{2}:\d{2}[\.,]\d{3})\s-->\s(?P<t2>\d{2}:\d{2}:\d{2}[\.,]\d{3})(?:.*(line:(?P<pos>[0-9.]+?))%)?', line)
            m = re.match(r'(?P<t1>(\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s-->\s(?P<t2>(\d{2}:)?\d{2}:\d{2}[\.,]\d{3})(?:.*(line:(?P<pos>[0-9.]+?))%)?', line)
            if m:
                time1 = m.group('t1').replace(',', '.')
                time2 = m.group('t2').replace(',', '.')
                if len(time1) == 9: time1 = "00:" + time1
                if len(time2) == 9: time2 = "00:" + time2
                entry = {}
                entry['ms_begin'] = self._tc.timeexpr_to_ms(time1)
                entry['ms_end'] = self._tc.timeexpr_to_ms(time2)
                entry['position'] = 'top' if m.group('pos') and float(m.group('pos')) < 50 else 'bottom'
                text = ""
                while i < len(lines):
                    line = lines[i].strip()

                    # Remove <c> </c> tags
                    line = re.sub('</??c.*?>', '', line)

                    i += 1
                    if line:
                        if text: text += "\n"
                        text += line
                    else:
                        break
                entry['text'] = unescape_text(text)
                self.entries.append(entry)
        self._apply_options()

    def generate_srt(self):
        """Return a string with the generated subtitle document in srt format."""

        srt_format_str = '{}\r\n{} --> {}\r\n{}\r\n\r\n'
        res = ''
        entry_count = 1
        for entry in self.entries:
            text = entry['text'].replace("\n", "\r\n")

            if not self.allow_italics:
                text = re.sub(r'<i>|</i>', '', text)

            # Remove <c> </c> tags
            text = re.sub('</??c.*?>', '', text)

            if self.allow_top_pos and entry['position'] == 'top':
                text = Ttml2Ssa.TOP_MARKER + text

            res += srt_format_str.format(entry_count, \
                                         self._tc.ms_to_subrip(entry['ms_begin']), \
                                         self._tc.ms_to_subrip(entry['ms_end']), \
                                         text)
            entry_count += 1
        return res

    def generate_vtt(self):
        """Return a string with the generated subtitle document in vtt format."""

        vtt_format_str = '{} --> {} {}\n{}\n\n'
        res = 'WEBVTT\n\n'

        for entry in self.entries:
            text = entry['text'].replace('\r', '')

            if not self.allow_italics:
                text = re.sub(r'<i>|</i>', '', text)

            # Remove <c> </c> tags
            text = re.sub('</??c.*?>', '', text)

            pos_str = 'line:90%,end'
            if self.allow_top_pos and entry['position'] == 'top':
                pos_str = 'line:10%,start'

            res += vtt_format_str.format(self._tc.ms_to_subrip(entry['ms_begin']).replace(',','.'), \
                                         self._tc.ms_to_subrip(entry['ms_end']).replace(',','.'), \
                                         pos_str, text)
        return res

    def _paragraphs_to_ssa(self, timestamp_min_sep=200):
        def fix_timestamps_separation(entries, timestamp_min_sep):
            for i in range(len(entries)):
                if i == 0: continue
                diff = entries[i]['ms_begin'] - entries[i-1]['ms_end']
                if diff < timestamp_min_sep:
                    s = round((timestamp_min_sep - diff) / 2)
                    entries[i]['ms_begin'] += s
                    entries[i-1]['ms_end'] -= s
                    if entries[i-1]['ms_end'] < 0: entries[i-1]['ms_end'] = 0

        entries = deepcopy(self.entries)
        if self.allow_timestamp_manipulation and timestamp_min_sep > 0:
            fix_timestamps_separation(entries, timestamp_min_sep)

        ssa_format_str = 'Dialogue: 0,{},{},Default,,0,0,0,,{}\r\n'
        res = ""
        for entry in entries:
            text = entry['text']
            if not self.allow_italics:
                text = re.sub(r'<i>|</i>', '', text)

            for tag in [('\n', '\\\\N'),
                        ('<i.*?>', '{\\\\i1}'), ('</i>', '{\\\\i0}'),
                        ('<b.*?>', '{\\\\b1}'), ('</b>', '{\\\\b0}'),
                        ('<u.*?>', '{\\\\u1}'), ('</u>', '{\\\\u0}'),
                        ('<.*?>', '')]:
                text = re.sub(tag[0], tag[1], text)

            if self.allow_top_pos and entry['position'] == 'top':
                text = Ttml2Ssa.TOP_MARKER + text

            res += ssa_format_str.format(self._tc.ms_to_ssa(entry['ms_begin']), self._tc.ms_to_ssa(entry['ms_end']), text)
        return res

    def generate_ssa(self):
        """Return a string with the generated subtitle document in ssa format."""

        res = "[Script Info]\r\n" \
            "ScriptType: v4.00+\r\n" \
            "Collisions: Normal\r\n" \
            "PlayDepth: 0\r\n" \
            "PlayResX: {}\r\n" \
            "PlayResY: {}\r\n" \
            "ScaledBorderAndShadow: yes\r\n\r\n" \
            "[V4+ Styles]\r\n" \
            "Format: Name,{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}\r\n" \
            "Style: Default,{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}\r\n\r\n" \
            "[Events]\r\n" \
            "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\r\n" \
            .format(self.ssa_playresx, self.ssa_playresy, \
                    *list(self.ssa_style.keys()) + list(self.ssa_style.values()))

        res += self._paragraphs_to_ssa(self.ssa_timestamp_min_sep)
        return res

    def _shift_timestamps(self, milliseconds):
        self._printinfo("Shifting {} milliseconds".format(milliseconds))
        for entry in self.entries:
            entry['ms_begin'] += milliseconds
            entry['ms_end'] += milliseconds

    def _scale_timestamps(self, multiplier):
        self._printinfo("Scale factor: {}".format(multiplier))
        for entry in self.entries:
            entry['ms_begin'] *= multiplier
            entry['ms_end'] *= multiplier

    def _cosmetic_filter(self):
        total_count = 0
        for entry in self.entries:
            number_of_lines = len(entry['text'].splitlines())

            entry['text'], n_changes = re.subn('—', '-', entry['text'])
            total_count += n_changes
            entry['text'], n_changes = re.subn('―', '-', entry['text'])
            total_count += n_changes
            entry['text'], n_changes = re.subn('–', '-', entry['text'])
            total_count += n_changes

            # Sometimes, in amazon subtitles, the line break is missing when the 2nd line starts with '<i>-'
            if self.fix_amazon_errors and number_of_lines == 1:
                entry['text'], n_changes = re.subn(r'(\S)<i>-', r'\1\n<i>-', entry['text'])
                total_count += n_changes

            # Add an space between '-' and the first word
            entry['text'], n_changes = re.subn(r'^(<i>|</i>|)-(\S)', r'\1- \2', entry['text'], flags=re.MULTILINE)
            total_count += n_changes

            # Add missing '-' in the first line
            if re.match(r'^(?!(-)|<i>-).*?\n(-|<i>-)', entry['text']):
                entry['text'] = '- ' + entry['text']
                total_count += 1

            # If there's only one line and it starts with '-', remove it
            if number_of_lines == 1 and entry['text'].count('-') == 1 and \
               (entry['text'].startswith('- ') or entry['text'].startswith('<i>- ')):
                entry['text'] = entry['text'].replace('- ', '')
                total_count += 1

        self._printinfo("Cosmetic changes: {}".format(total_count))

    def _language_fix_filter(self):
        lang = self.subtitle_language or self.lang
        es_replacements = [('\xA8', '¿'), ('\xAD', '¡'), ('ń', 'ñ')]
        total_count = 0
        for entry in self.entries:
            if lang == 'es':
                for rep in es_replacements:
                    total_count += entry['text'].count(rep[0])
                    entry['text'] = entry['text'].replace(rep[0], rep[1])
            if lang == 'ar':
                from unicodedata import lookup
                # Netflix (vtt)
                if not '&lrm;' in entry['text'] and not '&rlm;' in entry['text']:
                    # Amazon
                    entry['text'], n_changes = re.subn(r'^(?!{}|{})'.format(lookup('RIGHT-TO-LEFT MARK'), lookup('RIGHT-TO-LEFT EMBEDDING')), lookup('RIGHT-TO-LEFT EMBEDDING'), entry['text'], flags=re.MULTILINE)
                    total_count += n_changes
                    total_count += entry['text'].count('?')
                    total_count += entry['text'].count(',')
                    entry['text'] = entry['text'].replace('?', '؟').replace(',', '،')

            # Netflix (vtt)
            if '&lrm;' in entry['text'] or '&rlm;' in entry['text']:
                from unicodedata import lookup
                entry['text'] = entry['text'].replace('&lrm;', lookup('LEFT-TO-RIGHT EMBEDDING'))
                entry['text'] = entry['text'].replace('&rlm;', lookup('RIGHT-TO-LEFT EMBEDDING'))

        self._printinfo("Replacements for language '{}': {}".format(lang, total_count))

    def _sequalize(self, entries):
        """ Combine parallel paragraphs """

        total_count = 0
        res = []

        for i in range(len(entries)):
            if i > 0 and entries[i]['ms_begin'] < entries[i-1]['ms_end']:
                entry = res.pop()
                if entries[i]['ms_end'] > entries[i-1]['ms_end']:
                    entry['ms_end'] = entries[i]['ms_end']
                entry['text'] += '\n' + entries[i]['text']
                res.append(entry)
                total_count += 1
            else:
                res.append(entries[i])

        if total_count:
            self._printinfo("Sequalized entries: {}".format(total_count))

        return res

    def _remove_duplicated(self, entries):
        """ Remove duplicated lines """

        total_count = 0
        res = []

        for i in range(len(entries)):
            if i > 0 and (entries[i]['text'] == entries[i-1]['text']) and \
                         ((entries[i]['ms_begin'] == entries[i-1]['ms_begin'] and entries[i]['ms_end'] == entries[i-1]['ms_end']) or \
                          (entries[i]['ms_begin'] == entries[i-1]['ms_end'])):
                res[-1]['ms_end'] = entries[i]['ms_end']
                total_count += 1
            else:
                res.append(entries[i])

        if total_count:
            self._printinfo("Duplicated entries removed: {}".format(total_count))

        return res

    def _printinfo(self, text):
        print(text)

    def write2file(self, output):
        """Write subtitle to file

        It will be saved as ssa, srt or vtt according to the output file extension.
        """

        extension = os.path.splitext(output)[1].lower()
        output_encoding = 'utf-8-sig'

        if extension == '.ssa' or extension == '.ass':
            res = self.generate_ssa()
        elif extension == '.vtt':
            res = self.generate_vtt()
            output_encoding = 'utf-8'
        else:
            res = self.generate_srt()

        with io.open(output, 'w', encoding=output_encoding, newline='') as handle:
            handle.write(res)

    def _read_file(self, filename, encoding=None):
        """ Try to read the file using the supplied encoding (if any), utf-8 and latin-1 """

        contents = ""

        encodings = ['utf-8', 'latin-1']
        if encoding:
            encodings.insert(0, encoding)

        for enc in encodings:
            try:
                self._printinfo("Opening file {} with encoding {}".format(filename, enc))
                with io.open(filename, 'r', encoding=enc) as handle:
                    contents = handle.read()
                    break
            except UnicodeDecodeError:
                self._printinfo("Error opening {}".format(filename))

        return contents

    def string_to_color(self, text):
        text = text.upper()
        if text.startswith('#'): text = text[1:]
        color_names = {
            # In BBGGRR
            'WHITE': 'FFFFFF',
            'BLANCO': 'FFFFFF',
            'GRAY': '808080',
            'GREY': '808080',
            'GRIS': '808080',
            'YELLOW': '00FFFF',
            'AMARILLO': '00FFFF',
            'RED': '0000FF',
            'ROJO': '0000FF',
            'GREEN': '00FF00',
            'VERDE': '00FF00',
            'BLUE': 'FF0000',
            'AZUL': 'FF0000',
            'BROWN': '2A2AA5',
            'MARRON': '2A2AA5',
            'BLACK': '000000',
            'NEGRO': '000000'
        }
        if text in color_names:
            text = color_names[text]

        try:
            number = int(text, base=16)
        except:
            self._printinfo('Warning: color {} is not recognized'.format(text))
            number = 0xffffff # White

        hex_number = "&H" + format(number, '08x').upper()
        return hex_number

    @staticmethod
    def _snake_to_camel(s):
        camel = ''
        for c in s:
            d = ord(c)
            if d < 91 and d > 64:
                camel += '_' + c.lower()
            else:
                camel += c
        return camel

    @staticmethod
    def parse_m3u8_from_string(m3u8):
        """ Parse a m3u8 from a string a return a list of the segments """

        segments = []

        lines = m3u8.splitlines()
        duration = 0
        discontinuity = False
        for line in lines:
            m = re.match(r'#EXTINF:([0-9.]+),', line)
            if m:
                duration = float(m.group(1))
            if line.startswith('#EXT-X-DISCONTINUITY'):
                discontinuity = True
            if not line.startswith('#'):
                segment = {}
                segment['url'] = line
                segment['duration'] = duration
                segment['discontinuity'] = discontinuity
                segments.append(segment)
                duration = 0
                discontinuity = False

        return segments

    def download_m3u8_subtitle(self, url):
        """ Download all segments from a m3u8 file and joins them together.
        Return a string with the subtitle and a list of the segments.
        """

        import requests

        baseurl = os.path.dirname(url)
        self._printinfo('Downloading {}'.format(url))
        #self._printinfo('baseurl: {}'.format(baseurl))
        r = requests.get(url, allow_redirects=True)
        segments = Ttml2Ssa.parse_m3u8_from_string(r.content.decode('utf-8'))
        #self._printinfo('segments: {}'.format(json.dumps(segments, sort_keys=True, indent=4)))
        self._printinfo('segments: {}'.format(json.dumps(segments)))

        res = ''
        for segment in segments:
            url = baseurl +'/'+ segment['url']
            self._printinfo('Downloading segment: {}'.format(os.path.basename(url)))
            r = requests.get(url, allow_redirects=True)
            res += r.content.decode('utf-8')

        return res, segments

    def download_m3u8_disney(self, url):
        """ Similar to download_m3u8_subtitle but specific for Disney+
        Download all segments from a m3u8 file and joins them together.
        Return a string with the subtitle and the offset (in milliseconds)
        that must be added to the timestamps.
        """

        if self.cache_downloaded_subtitles and self.cache_directory:
            vtt, offset = self._load_vtt_from_cache(url)
            if vtt:
                return vtt, offset

        vtt, segments = self.download_m3u8_subtitle(url)
        offset = 0
        if len(segments) > 1 and segments[1]['discontinuity']:
            offset = segments[0]['duration'] * 1000
        self._printinfo("offset: {}".format(offset))

        if self.cache_downloaded_subtitles and self.cache_directory:
            self._save_vtt_to_cache(url, vtt, offset)

        return vtt, offset

    def _cache_filename(self, url):
        import hashlib
        id = re.sub(r'(?:https|http)://.*?/', '', url)
        self._printinfo('cache id: {}'.format(id))
        md5sum = hashlib.md5(id.encode('utf-8')).hexdigest()
        return '{}{}{}.json'.format(self.cache_directory, os.path.sep, md5sum)

    def _save_vtt_to_cache(self, url, vtt, offset):
        filename = self._cache_filename(url)
        self._printinfo('Saving {}'.format(filename))

        data = {}
        data['data'] = vtt
        data['offset'] = offset

        with io.open(filename, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(data, ensure_ascii=False))

    def _load_vtt_from_cache(self, url):
        filename = self._cache_filename(url)
        if os.path.exists(filename):
            self._printinfo('Loading {}'.format(filename))
            with io.open(filename, 'r', encoding='utf-8') as handle:
                data = json.loads(handle.read())
                return data['data'], data['offset']
        return '', 0

    @staticmethod
    def get_subtitle_list_from_m3u8_string(doc, language_list=None, allow_forced=True, allow_non_forced=True, baseurl='', sort=True):
        """ Parse a m3u8 file, look for subtitles and return a list of them """

        def lang_allowed(lang, lang_list):
            if not lang_list:
                return True

            lang = lang.lower()

            for l in lang_list:
                if lang.startswith(l.lower()):
                    return True

            return False

        sub_list = []
        lines = doc.splitlines()
        tag = '#EXT-X-MEDIA:TYPE=SUBTITLES,'
        for line in lines:
            if line.startswith(tag):
                sub = {}
                sub['lang'] = ''
                sub['name'] = ''
                sub['forced'] = False
                sub['url'] = ''
                line = line.replace(tag, '')
                params = line.split(',')

                for param in params:
                    if '=' in param:
                        name, value = param.split('=', 1)
                        value = value.replace('"', '')
                        if name == 'LANGUAGE': sub['lang'] = value
                        elif name == 'NAME': sub['name'] = value
                        elif name == 'FORCED' and value == 'YES': sub['forced'] = True
                        elif name == 'URI': sub['url'] = baseurl + value

                if sub['url'] and sub['name'] and sub['lang']:
                    sub['impaired'] = 'CC' in sub['name']
                    sub['filename'] = '{}{}{}'.format(sub['lang'], '.[CC]' if sub['impaired'] else '', '.forced' if sub['forced']  else '')
                    if lang_allowed(sub['lang'], language_list) and ((allow_forced and sub['forced']) or (allow_non_forced and not sub['forced'])):
                        sub_list.append(sub)

        if sort:
            sub_list = sorted(sub_list, key=lambda x: x['lang'].replace('-419', '-lat') +" "+ str(int(x['forced'])))

        return sub_list

    def get_subtitle_list_from_m3u8_url(self, url, language_list=None, allow_forced=True, allow_non_forced=True):
        """ Download the m3u8 file from the url, look for subtitles in the file and return a list of them """

        import requests
        self._printinfo('Downloading {}'.format(url))
        baseurl = os.path.dirname(url) + '/'
        r = requests.get(url, allow_redirects=True)
        sub_list = Ttml2Ssa.get_subtitle_list_from_m3u8_string(r.content.decode('utf-8'), language_list, allow_forced, allow_non_forced, baseurl)
        return sub_list


class Ttml2SsaAddon(Ttml2Ssa):
    def __init__(self, shift=0, source_fps=23.976, scale_factor=1, subtitle_language=None):
        super(Ttml2SsaAddon, self).__init__(shift, source_fps, scale_factor, subtitle_language)
        self.addon = Ttml2SsaAddon._addon()

        try:  # Kodi >= 19
            from xbmcvfs import translatePath
        except ImportError:  # Kodi 18
            from xbmc import translatePath

        self.cache_directory = translatePath(self.addon.getAddonInfo('profile')) + "subtitles" + os.sep
        self._printinfo("Cache directory: {}".format(self.cache_directory))
        if not os.path.exists(os.path.dirname(self.cache_directory)):
            os.makedirs(os.path.dirname(self.cache_directory))
        self.cache_downloaded_subtitles = True

        self._load_settings()

    def _load_settings(self):
        self.ssa_style["Fontname"] = self.addon.getSetting('fontname')
        self.ssa_style["Fontsize"] = self.addon.getSettingInt('fontsize')
        self.ssa_style["PrimaryColour"] = self.string_to_color(self.addon.getSetting('primarycolor'))
        self.ssa_style["BackColour"] = self.string_to_color(self.addon.getSetting('backcolor'))
        self.ssa_style["OutlineColour"] = self.string_to_color(self.addon.getSetting('outlinecolor'))
        self.ssa_style["BorderStyle"] = 1 if self.addon.getSettingInt('borderstyle') == 0 else 3
        self.ssa_style["Outline"] = self.addon.getSettingInt('outline')
        self.ssa_style["Shadow"] = self.addon.getSettingInt('shadow')
        self.ssa_style["Bold"] = -1 if self.addon.getSettingBool('bold') else 0
        self.ssa_style["Italic"] = -1 if self.addon.getSettingBool('italic') else 0
        self.ssa_style["MarginL"] = self.addon.getSettingInt('marginl')
        self.ssa_style["MarginR"] = self.addon.getSettingInt('marginr')
        self.ssa_style["MarginV"] = self.addon.getSettingInt('marginv')
        self.use_cosmetic_filter = self.addon.getSettingBool('cosmetic_filter')
        self.use_language_filter = self.addon.getSettingBool('language_filter')
        self.fix_amazon_errors = self.addon.getSettingBool('fix_amazon')
        self.cache_downloaded_subtitles = self.addon.getSettingBool('cache_downloaded')
        self.ssa_timestamp_min_sep = self.addon.getSettingInt('min_sep')
        self.allow_italics = self.addon.getSettingBool('allow_italics')
        self.allow_top_pos = self.addon.getSettingBool('allow_top_pos')
        self.allow_timestamp_manipulation = self.addon.getSettingBool('timestamp manipulation')
        self.fix_timestamp_collisions = self.addon.getSettingBool('fix_collisions')
        self.fix_duplicated_entries = False
        self._printinfo("Subtitle type: {}".format(self.subtitle_type()))
        self._printinfo("SSA style: {}".format(self.ssa_style))
        self._printinfo("Cosmetic filter: {}".format("yes" if self.use_cosmetic_filter else "no"))
        self._printinfo("Language filter: {}".format("yes" if self.use_language_filter else "no"))
        self._printinfo("Fix Amazon errors: {}".format("yes" if self.fix_amazon_errors else "no"))
        self._printinfo("Cache downloaded subtitles: {}".format("yes" if self.cache_downloaded_subtitles else "no"))
        self._printinfo("Timestamp minimum separation: {}".format(self.ssa_timestamp_min_sep))

    def subtitle_type(self):
        """ Return the user's preferred subtitle type.
        Posible values: srt, ssa, both
        """

        return Ttml2SsaAddon.subtitle_type()

    @staticmethod
    def _addon():
        import xbmcaddon
        return xbmcaddon.Addon('script.module.ttml2ssa')

    @staticmethod
    def subtitle_type():
        """ Return the user's preferred subtitle type.
        Posible values: srt, ssa, both
        """

        addon = Ttml2SsaAddon._addon()
        return ['ssa', 'srt', 'both'][addon.getSettingInt('subtitle_type')]

    def _printinfo(self, text):
        """ Print info in the kodi log """

        import xbmc
        xbmc.log("Ttml2Ssa: {}".format(text), xbmc.LOGINFO)
