# DataBeat OS audio pattern backup

DataBeat OS provides audio export for the first-generation Volca Sample. The
stock instrument's MIDI input and headphone output allow a complete pattern
backup without a MIDI OUT hardware modification.

Stored slots are copied from flash, so one valid session may contain patterns
in more than one format. Studio retains all eleven payloads exactly and labels
each format separately; this does not permit combining different session IDs.
Studio restores only memories in the DataBeat OS 1.0 pattern format; memories in
another format stay in the bank byte for byte but cannot be restored. See
[pattern banks](patterns.md) for the managed archive and memory selection.

The export contains stored slots 0–9 and a separate snapshot of the current
edit buffer. Every pattern retains all 2624 bytes, including DataBeat OS microtiming,
echo/ratchet maps, Predictability and packed motion, unknown bytes and padding. Stored patterns are
read directly from flash. The edit-buffer snapshot merges the current controls
and motion masks into a private copy using the native serializer's rules;
export does not save it or alter the live pattern/runtime controls.

Studio records mono PCM16 from the selected audio input, requests the export
over MIDI and decodes the recording incrementally. A bank is usable only after
all eleven frames arrive in order with one session ID, a valid current-pattern signature
and matching CRCs. A missing, duplicated, corrupted or mixed-session frame
rejects the entire capture. A completed audio capture is evidence that those
pattern bytes were received; it is not evidence of a later restore to hardware.

The firmware stops the native sequencer and fades remaining voices before
starting export. During export it suspends pattern editing, sample/SYRO work
and flash writes. MIDI Stop cancels it. Cleanup clears the temporary effect
workspace, preserves effect coefficients and resumes the previous audio state;
an active DataBeat OS delay restarts with an empty ring. No new permanent RAM or heap
is allocated. The original audio interrupt keeps its DAC/ADC housekeeping;
the wrapper replaces its next stereo output words with the mono backup tone.

Uninitialized stored slots and the two opaque original Korg OK GO templates
are preserved exactly. Selecting such a slot initializes the Volca live buffer
with native defaults; backup and restore retain the original stored bytes.

## Wire format

The MIDI request is `F0 42 30 00 01 2D 7D F7`. It uses a private DataBeat OS command,
with no payload. Firmware chooses a fresh 32-bit session ID from its timer.

At a nominal 31,250 audio samples per second, one bit occupies twelve samples.
Space (0) uses one sine cycle per bit, approximately 2604.17 Hz. Mark (1) uses
two cycles, approximately 5208.33 Hz. The sine table has amplitude 2000 in signed
PCM16 units. Every byte is UART 8N1, least-significant bit first: start 0,
eight data bits, stop 1. Each frame begins with 48 bytes of `55`; idle gaps use
mark. Twenty-four mark symbols follow the final frame. The nominal complete
bank lasts approximately 114 seconds, plus short main-loop preparation gaps.

Each frame contains this 16-byte little-endian header, the unmodified pattern
payload, then a four-byte little-endian standard CRC32 of header plus payload:

| Offset | Bytes | Meaning |
| --- | --- | --- |
| 0 | 4 | ASCII `LMBA` |
| 4 | 1 | Protocol version, 1 |
| 5 | 1 | Frame index: 0–9 stored slots; 10 current edit buffer |
| 6 | 1 | Frame count, 11 |
| 7 | 1 | Flags: bit 0 set only for current frame; remaining bits zero |
| 8 | 2 | Payload length, 2624 |
| 10 | 2 | Reserved, zero |
| 12 | 4 | Session ID, identical in all eleven frames |

The decoder accepts mono PCM16 WAV or incremental little-endian PCM16 chunks.
It adapts to capture rate and instrument clock variation using interpolated
positive zero crossings. A rolling forty-symbol `LMBA` match establishes the
UART byte boundary: the alternating `55` preamble alone has no unique boundary.
Per-byte synchronization prevents timing drift accumulating over the bank.
Small waveform noise and capture resampling are covered by synthetic tests;
physical input gain, device clock frequency and electrical audio routing still
need an explicitly authorized hardware test.

## Offline verification

`python3 -m unittest discover -s tests -p test_pattern_audio.py -v` verifies
complete byte-preserving captures at 44.1/48 kHz, clock variation, arbitrary
phase, noise, CRC/header/session/order failures and truncation. Fixtures are
generated in memory or temporary files and are never played.

The firmware project's motion/storage integration tests execute the actual
Thumb backup snapshot, and Studio tests decode complete synthetic eleven-frame
banks with Predictability and motion intact, including mixed-format
archives. Native SYRO output is independently decoded to check all 2624 restored
bytes. The
current snapshot is checked against both an independent reference and the
native serializer. Tests also cover refusal while native work is pending,
abort cleanup, coefficient preservation, memory bounds, callee-save ABI and
bounded tick instructions. These are emulator checks, not physical flash,
audio playback or recording tests.
