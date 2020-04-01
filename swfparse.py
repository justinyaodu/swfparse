"""A simple parser for SWF files."""

def byte_align(pos):
    """Return the smallest multiple of 8 greater than ``pos``. Raises
    ``ValueError`` if ``pos`` is negative.
    """
    if pos < 0:
        msg = "Expected positive integer, got {}"
        raise ValueError(msg.format(pos))
    return ((pos + 7) // 8) * 8


def get_bit(data, pos):
    byte_index, bit_index = divmod(pos, 8)
    byte = data[byte_index]
    return (byte >> (7 - bit_index)) & 1, pos + 1


def _check_byte_alignment(pos):
    if pos % 8 != 0:
        msg = "Position not byte aligned: {}"
        raise ValueError(msg.format(pos))


def get_byte(data, pos):
    _check_byte_alignment(pos)
    return data[pos // 8], pos + 8


def parse_bytes(data, pos, num_bytes):
    _check_byte_alignment(pos)
    return data[pos // 8 : (pos // 8) + num_bytes], pos + 8 * num_bytes


def as_signed(num, num_bits):
    """Interpret the bit pattern of the unsigned integer ``num`` as a
    signed two's complement integer.
    """
    if num & (1 << (num_bits - 1)) != 0: # if sign bit set
        return num - (1 << num_bits)
    else:
        return num


def parse_ub(data, pos, num_bits):
    result = 0
    for _ in range(0, num_bits):
        bit, pos = get_bit(data, pos)
        result = (2 * result) + bit
    return result, pos


def parse_sb(data, pos, num_bits):
    ub, pos = parse_ub(data, pos, num_bits)
    return as_signed(ub, num_bits), pos


def parse_fb(data, pos, num_bits):
    sb, pos = parse_sb(data, pos, num_bits)
    return sb / (2 ** 16), pos


def parse_uint(data, pos, num_bytes):
    pos = byte_align(pos)
    result = 0
    for byte_index in range(0, num_bytes):
        byte, pos = get_byte(data, pos)
        result |= byte << (8 * byte_index)
    return result, pos


def parse_ui8(data, pos):
    return parse_uint(data, pos, 1)


def parse_ui16(data, pos):
    return parse_uint(data, pos, 2)


def parse_ui32(data, pos):
    return parse_uint(data, pos, 4)


def parse_ui64(data, pos):
    return parse_uint(data, pos, 8)


def parse_si8(data, pos):
    ui8, pos = parse_ui8(data, pos)
    return as_signed(ui8, 8), pos


def parse_si16(data, pos):
    ui16, pos = parse_ui16(data, pos)
    return as_signed(ui16, 16), pos


def parse_si32(data, pos):
    ui32, pos = parse_ui32(data, pos)
    return as_signed(ui32, 32), pos


def parse_fixed8(data, pos):
    si16, pos = parse_si16(data, pos)
    return si16 / (2 ** 8), pos


def parse_fixed16(data, pos):
    si32, pos = parse_si32(data, pos)
    return si32 / (2 ** 16), pos


class Rect:
    @staticmethod
    def parse(data, pos):
        rect = Rect()
        num_bits, pos = parse_ub(data, pos, 5)
        rect.x_min, pos = parse_sb(data, pos, num_bits)
        rect.x_max, pos = parse_sb(data, pos, num_bits)
        rect.y_min, pos = parse_sb(data, pos, num_bits)
        rect.y_max, pos = parse_sb(data, pos, num_bits)
        return rect, pos

    def __repr__(self):
        return "Rect({}, {}, {}, {})".format(
                self.x_min,
                self.x_max,
                self.y_min,
                self.y_max)


class Header:
    def __init__(self, signature):
        self.signature = signature

        actual_ending = signature[1:]
        expected_ending = 'WS'
        if actual_ending != expected_ending:
            msg = "Header signature is invalid; expected '{}', got '{}'"
            raise ValueError(msg.format(expected_ending, actual_ending))

        if signature[0] == 'F':
            self.compression = None
        elif signature[0] == 'C':
            self.compression = 'zlib'
        elif signature[0] == 'Z':
            self.compression = 'lzma'
        else:
            msg = "Unknown compression type specified in header: '{}'"
            raise ValueError(msg.format(header.signature[0]))
    
    @staticmethod
    def parse(data, pos):
        sig_byte_1, pos = parse_ui8(data, pos)
        sig_byte_2, pos = parse_ui8(data, pos)
        sig_byte_3, pos = parse_ui8(data, pos)
        header = Header(chr(sig_byte_1) + chr(sig_byte_2) + chr(sig_byte_3))

        header.version,     pos = parse_ui8(data, pos)
        header.file_length, pos = parse_ui32(data, pos)

        if header.compression is None:
            header.frame_size,  pos = Rect.parse(data, pos)
            header.frame_rate,  pos = parse_fixed8(data, pos)
            header.frame_count, pos = parse_ui16(data, pos)

        return header, pos


class Tag:
    _types_by_num = {}

    def __init_subclass__(cls, /, num, **kwargs):
        super().__init_subclass__(**kwargs)
        Tag._types_by_num[num] = cls

    def __init__(self, type_num, length):
        self.type_num = type_num
        self.length = length

    def _parse(self, data, pos):
        self.data = parse_bytes(data, pos, self.length)

    @staticmethod
    def parse(data, pos):
        type_and_length, pos = parse_ui16(data, pos)
        type_num = type_and_length >> 6

        length = type_and_length & 0x3F
        if length == 0x3F:
            length, pos = parse_ui32(data, pos)

        try:
            tag_class = Tag._types_by_num[type_num]
            tag = tag_class(type_num, length)
        except KeyError:
            tag = Tag(type_num, length)

        tag._parse(data, pos)

        return tag, pos + 8 * length


class End(Tag, num=0): pass
class ShowFrame(Tag, num=1): pass
class DefineShape(Tag, num=2): pass
class PlaceObject(Tag, num=4): pass
class RemoveObject(Tag, num=5): pass
class DefineBits(Tag, num=6): pass
class DefineButton(Tag, num=7): pass
class JPEGTables(Tag, num=8): pass
class SetBackgroundColor(Tag, num=9): pass
class DefineFont(Tag, num=10): pass
class DefineText(Tag, num=11): pass
class DoAction(Tag, num=12): pass
class DefineFontInfo(Tag, num=13): pass


class DefineSound(Tag, num=14):
    _formats = {
        0: 'uncompressed native-endian',
        1: 'ADPCM',
        2: 'MP3',
        3: 'uncompressed little-endian',
        4: 'Nellymoser 16 kHz',
        5: 'Nellymoser 8 kHz',
        6: 'Nellymoser',
        11: 'Speex',
    }

    _sampling_rates = {
        0: 5512.5,
        1: 11025,
        2: 22050,
        3: 44100,
    }

    _bits_per_sample = {
        0: 8,
        1: 16,
    }

    _channels = {
        0: 'mono',
        1: 'stereo',
    }

    def _parse(self, data, pos):
        original_pos = pos

        self.id, pos = parse_ui16(data, pos)

        format_num, pos = parse_ub(data, pos, 4)
        self.format = DefineSound._formats[format_num]

        sampling_rate_num, pos = parse_ub(data, pos, 2)
        self.sampling_rate = DefineSound._sampling_rates[sampling_rate_num]

        bits_per_sample_num, pos = parse_ub(data, pos, 1)
        self.bits_per_sample = DefineSound._bits_per_sample[bits_per_sample_num]

        channels_num, pos = parse_ub(data, pos, 1)
        self.channels = DefineSound._channels[channels_num]

        self.sample_count, pos = parse_ui32(data, pos)

        data_length = self.length - ((pos - original_pos) // 8)
        self.data, pos = parse_bytes(data, pos, data_length)


class StartSound(Tag, num=15): pass
class DefineButtonSound(Tag, num=17): pass
class SoundStreamHead(Tag, num=18): pass
class SoundStreamBlock(Tag, num=19): pass
class DefineBitsLossless(Tag, num=20): pass
class DefineBitsJPEG2(Tag, num=21): pass
class DefineShape2(Tag, num=22): pass
class DefineButtonCxform(Tag, num=23): pass
class Protect(Tag, num=24): pass
class PlaceObject2(Tag, num=26): pass
class RemoveObject2(Tag, num=28): pass
class DefineShape3(Tag, num=32): pass
class DefineText2(Tag, num=33): pass
class DefineButton2(Tag, num=34): pass
class DefineBitsJPEG3(Tag, num=35): pass
class DefineBitsLossless2(Tag, num=36): pass
class DefineEditText(Tag, num=37): pass
class DefineSprite(Tag, num=39): pass
class FrameLabel(Tag, num=43): pass
class SoundStreamHead2(Tag, num=45): pass
class DefineMorphShape(Tag, num=46): pass
class DefineFont2(Tag, num=48): pass
class ExportAssets(Tag, num=56): pass
class ImportAssets(Tag, num=57): pass
class EnableDebugger(Tag, num=58): pass
class DoInitAction(Tag, num=59): pass
class DefineVideoStream(Tag, num=60): pass
class VideoFrame(Tag, num=61): pass
class DefineFontInfo2(Tag, num=62): pass
class EnableDebugger2(Tag, num=64): pass
class ScriptLimits(Tag, num=65): pass
class SetTabIndex(Tag, num=66): pass
class FileAttributes(Tag, num=69): pass
class PlaceObject3(Tag, num=70): pass
class ImportAssets2(Tag, num=71): pass
class DefineFontAlignZones(Tag, num=73): pass
class CSMTextSettings(Tag, num=74): pass
class DefineFont3(Tag, num=75): pass
class SymbolClass(Tag, num=76): pass
class Metadata(Tag, num=77): pass
class DefineScalingGrid(Tag, num=78): pass
class DoABC(Tag, num=82): pass
class DefineShape4(Tag, num=83): pass
class DefineMorphShape2(Tag, num=84): pass
class DefineSceneAndFrameLabelData(Tag, num=86): pass
class DefineBinaryData(Tag, num=87): pass
class DefineFontName(Tag, num=88): pass
class StartSound2(Tag, num=89): pass
class DefineBitsJPEG4(Tag, num=90): pass
class DefineFont4(Tag, num=91): pass
class EnableTelemetry(Tag, num=93): pass


class SWFData:
    def __init__(self, data):
        pos = 0
        self.header, pos = Header.parse(data, pos)

        if self.header.compression is None:
            self.tags = []
            while pos // 8 < len(data):
                tag, pos = Tag.parse(data, pos)
                self.tags.append(tag)

