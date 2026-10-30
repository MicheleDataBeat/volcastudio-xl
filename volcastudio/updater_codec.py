"""Volca Sample system-updater audio: decoding and template-preserving encoding.

The updater is stereo PCM16 at 44,100 Hz. Each eight-frame cycle carries one
symbol per channel; packets are separated by gap cycles. Re-encoding keeps the
PCM of every unchanged packet of the template, so a firmware image built from a
user's own updater differs from it only in the pages that actually changed.
No playback or device access happens here.
"""
import array
import struct
import sys
import wave
from dataclasses import dataclass
from io import BytesIO

PAGE_SIZE = 256
IMAGE_SIZE = 0x20000
SYMBOL_FRAMES = 8
SIN = (0, 23169, 32767, 23169, 0, -23169, -32767, -23169)
ECC_BASIS = (0x55, 0x56, 0x59, 0x5a, 0x65, 0x66, 0x69, 0x6a)
GAP_SYMBOL = 0x11
START_MARKS = (0x55, 0x01)
HEADER_MAGIC = b'\xa9KORG SYSTEM FILE'
VOLCA_SAMPLE_TARGET = bytes.fromhex('b83300ff') + b'\x00\xff'


class CodecError(ValueError):
    pass


def crc16(payload):
    """CRC16-CCITT, polynomial 0x1021, initial 0xffff, no reflection/xor."""
    crc = 0xffff
    for value in payload:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xffff
    return crc


def ecc24(payload):
    """256-byte Hamming ECC as used by the SYRO transport, little-endian wire order."""
    if len(payload) != PAGE_SIZE:
        raise CodecError('ECC requires a 256-byte page')
    r1 = r2 = r3 = 0
    for index, byte in enumerate(payload):
        ci = 0
        for bit, basis in enumerate(ECC_BASIS):
            if byte & (1 << bit):
                ci ^= basis
        r1 ^= ci
        if ci & 0x40:
            r3 ^= index
            r2 ^= (~index) & 0xff
    interleaved = 0
    for bit in range(7, -1, -1):
        interleaved = (interleaved << 1) | ((r3 >> bit) & 1)
        interleaved = (interleaved << 1) | ((r2 >> bit) & 1)
    return bytes((interleaved >> 8, interleaved & 0xff, ((r1 << 2) | 3) & 0xff))


def data_packet(payload):
    if len(payload) != PAGE_SIZE:
        raise CodecError('Data packet requires a 256-byte page')
    return b'\xa9' + bytes(payload) + ecc24(payload) + struct.pack('<H', crc16(payload))


def fill_packet(value):
    return bytes((0x4e, value, value ^ 0xff))


def header_packet(version, size=IMAGE_SIZE):
    packet = bytearray(35)
    packet[:17] = HEADER_MAGIC
    packet[17:23] = VOLCA_SAMPLE_TARGET
    packet[23:25] = bytes(version)
    struct.pack_into('<I', packet, 25, size)
    struct.pack_into('<H', packet, 33, crc16(packet[1:33]))
    return bytes(packet)


def packet_symbols(packet):
    """Six LSB-first bits per cycle: the first three on L, the next three on R."""
    bits = int.from_bytes(packet, 'little')
    output = []
    for shift in range(0, ((len(packet) * 8 + 5) // 6) * 6, 6):
        six = (bits >> shift) & 0x3f
        output.append(((six & 7) << 4) | (six >> 3))
    return output


def modulate_symbols(symbols):
    """Raw shaped QAM with floor rounding and no low-pass filter."""
    samples = array.array('h')
    for combined in symbols:
        cycles = []
        for channel in (0, 1):
            symbol = (combined >> (4 if channel == 0 else 0)) & 7
            phase = symbol >> 1
            volume = 16 if symbol & 1 else 4
            cycle = []
            for index in range(SYMBOL_FRAMES):
                sample = SIN[(phase * 2 + index) & 7]
                if sample > 0:
                    sample = 32767 - ((32767 - sample) ** 2 // 32767)
                elif sample < 0:
                    sample = ((sample + 32767) ** 2 // 32767) - 32767
                cycle.append(sample * volume // 24)
            cycles.append(cycle)
        for index in range(SYMBOL_FRAMES):
            samples.extend((cycles[0][index], cycles[1][index]))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


def modulate_packet(packet):
    return modulate_symbols(packet_symbols(packet))


@dataclass(frozen=True)
class Packet:
    gap_cycles: int
    payload: bytes
    start_cycle: int
    data_cycles: int


@dataclass(frozen=True)
class Transfer:
    packets: tuple
    footer_cycles: int
    pcm: bytes
    wav: bytes

    def binary(self):
        return b''.join(page_payload(p.payload) for p in self.packets[1:])

    @property
    def version(self):
        return tuple(self.packets[0].payload[23:25])


def page_payload(packet):
    if len(packet) == 262 and packet[0] == 0xa9:
        payload = packet[1:257]
        if crc16(payload) != struct.unpack_from('<H', packet, 260)[0]:
            raise CodecError('Data CRC mismatch')
        if ecc24(payload) != packet[257:260]:
            raise CodecError('Data ECC mismatch')
        return payload
    if len(packet) == 3 and packet[0] == 0x4e:
        if packet[1] ^ packet[2] != 0xff:
            raise CodecError('Fill complement mismatch')
        return bytes((packet[1],)) * PAGE_SIZE
    raise CodecError('Invalid firmware page packet')


# The exact RIFF layout of Korg's updaters: a 44-byte header, PCM data chunk.
def _riff(pcm):
    return (b'RIFF' + struct.pack('<I', len(pcm) + 36) + b'WAVEfmt ' +
            struct.pack('<IHHIIHH', 16, 1, 2, 44100, 44100 * 4, 4, 16) +
            b'data' + struct.pack('<I', len(pcm)) + pcm)


def _pcm(raw):
    if raw[:4] != b'RIFF' or raw[8:12] != b'WAVE' or raw[36:40] != b'data':
        raise CodecError('Unsupported updater WAV layout')
    with wave.open(BytesIO(raw), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                stream.getcomptype()) != (2, 2, 44100, 'NONE'):
            raise CodecError('Only stereo 16-bit PCM 44100 Hz updaters are supported')
        frames = stream.getnframes()
        pcm = stream.readframes(frames)
    if frames % SYMBOL_FRAMES or len(pcm) != frames * 4:
        raise CodecError('Truncated or unaligned updater audio')
    return pcm


def _demodulate(pcm):
    samples = array.array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    symbols = []
    for offset in range(0, len(samples), 16):
        combined = 0
        for channel in (0, 1):
            x, y = samples[offset + 4 + channel], samples[offset + 8 + channel]
            if abs(x) >= abs(y):
                phase, magnitude = (0 if x >= 0 else 2), abs(x)
            else:
                phase, magnitude = (1 if y < 0 else 3), abs(y)
            combined = (combined << 4) | (phase << 1) | (magnitude > 13000)
        symbols.append(combined)
    return symbols


def decode(raw):
    """Decode a complete Volca Sample updater WAV given as bytes."""
    raw = bytes(raw)
    pcm = _pcm(raw)
    symbols = _demodulate(pcm)
    position = 0
    packets = []
    footer = 0
    while position < len(symbols):
        gap_start = position
        while position < len(symbols) and symbols[position] == GAP_SYMBOL:
            position += 1
        gap = position - gap_start
        if position == len(symbols):
            footer = gap
            break
        if gap < 20 or tuple(symbols[position:position + 2]) != START_MARKS:
            raise CodecError(f'Invalid gap or start marks at cycle {position}')
        position += 2
        first = symbols[position:position + 2]
        if len(first) != 2:
            raise CodecError('Truncated packet')
        marker = ((first[0] >> 4) | ((first[0] & 7) << 3) | ((first[1] >> 4) << 6)) & 0xff
        if not packets:
            count = 35
        elif marker == 0xa9:
            count = 262
        elif marker == 0x4e:
            count = 3
        else:
            raise CodecError(f'Unknown packet marker 0x{marker:02x}')
        cycles = (count * 8 + 5) // 6
        encoded = symbols[position:position + cycles]
        if len(encoded) != cycles:
            raise CodecError('Truncated packet body')
        bits = 0
        for index, symbol in enumerate(encoded):
            bits |= (((symbol >> 4) & 7) | ((symbol & 7) << 3)) << (index * 6)
        packet = (bits & ((1 << (count * 8)) - 1)).to_bytes(count, 'little')
        if bits >> (count * 8):
            raise CodecError('Nonzero terminal packet padding')
        if not packets:
            if packet[:17] != HEADER_MAGIC or packet[17:23] != VOLCA_SAMPLE_TARGET:
                raise CodecError('Not a first-generation Volca Sample system updater')
            if crc16(packet[1:33]) != struct.unpack_from('<H', packet, 33)[0]:
                raise CodecError('Header CRC mismatch')
        else:
            try:
                page_payload(packet)
            except CodecError as error:
                raise CodecError(f'Page {len(packets) - 1}: {error}') from error
        packets.append(Packet(gap, packet, position - 2, cycles))
        position += cycles
    if len(packets) != IMAGE_SIZE // PAGE_SIZE + 1 or footer < 3000:
        raise CodecError('Incomplete image or updater footer')
    if packets[0].gap_cycles < 10000 or packets[1].gap_cycles < 8000:
        raise CodecError('Missing long header or erase gap')
    return Transfer(tuple(packets), footer, pcm, raw)


def encode_from_template(template, image, version):
    """Re-encode `image` into the template's audio, replacing only changed packets.

    `template` is a decoded Transfer; `version` the two header version bytes.
    The result is decoded again and must reproduce the image and header exactly.
    """
    if len(image) != IMAGE_SIZE:
        raise CodecError('Expected a complete 128 KiB image')
    header = bytearray(template.packets[0].payload)
    header[23:25] = bytes(version)
    struct.pack_into('<H', header, 33, crc16(header[1:33]))
    frame = SYMBOL_FRAMES * 4
    first = template.packets[0]
    start = (first.start_cycle + 2) * frame
    cursor = start + first.data_cycles * frame
    pieces = [template.pcm[:start], modulate_packet(bytes(header))]
    for index, packet in enumerate(template.packets[1:]):
        block = image[index * PAGE_SIZE:(index + 1) * PAGE_SIZE]
        if block == page_payload(packet.payload):
            continue
        replacement = (fill_packet(block[0]) if len(packet.payload) == 3 and len(set(block)) == 1
                       else data_packet(block))
        start = (packet.start_cycle + 2) * frame
        pieces.extend((template.pcm[cursor:start], modulate_packet(replacement)))
        cursor = start + packet.data_cycles * frame
    pieces.append(template.pcm[cursor:])
    pcm = b''.join(pieces)
    # Keep the template's own 44-byte RIFF header; only the sizes change.
    riff = bytearray(template.wav[:44])
    struct.pack_into('<I', riff, 4, len(pcm) + 36)
    struct.pack_into('<I', riff, 40, len(pcm))
    wav = bytes(riff) + pcm
    check = decode(wav)
    if check.binary() != bytes(image) or check.packets[0].payload != bytes(header):
        raise CodecError('Re-encoded updater does not decode to the requested image')
    return wav


def synthetic_updater(image, version=(1, 42)):
    """A complete, decodable updater for offline tests; carries no real firmware."""
    if len(image) != IMAGE_SIZE:
        raise CodecError('Expected a complete 128 KiB image')
    gap = lambda cycles: [GAP_SYMBOL] * cycles
    symbols = gap(10000) + list(START_MARKS) + packet_symbols(header_packet(version))
    for index in range(IMAGE_SIZE // PAGE_SIZE):
        block = image[index * PAGE_SIZE:(index + 1) * PAGE_SIZE]
        packet = fill_packet(block[0]) if len(set(block)) == 1 else data_packet(block)
        symbols += gap(8000 if index == 0 else 20) + list(START_MARKS) + packet_symbols(packet)
    symbols += gap(3000)
    return _riff(modulate_symbols(symbols))
