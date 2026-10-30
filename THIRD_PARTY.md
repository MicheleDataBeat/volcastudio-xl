# Third-party components

VolcaStudio XL's own code, documentation and groove template catalog are
released under the [MIT License](LICENSE). The components below keep their own
terms.

## Korg SYRO SDK

The sample and pattern encoder uses source from the official
[Korg Volca Sample SDK](https://github.com/korginc/volcasample), revision
`b0ed615f18c230a18b378d9ddc6a936971597e4e`.

The minimal source bundle is under `vendor/korg-syro/`. Its upstream files are
unmodified, including copyright notices and the BSD-3-Clause
[license](vendor/korg-syro/COPYING). Exact input hashes are recorded in
[provenance](vendor/korg-syro/PROVENANCE.json). Sample assets and upstream
executables are excluded.

VolcaStudio XL compiles the encoder locally with `tools/build_syro.py`; packaged
builds contain that compiled converter. The SDK files and the converter built
from them remain under Korg's BSD-3-Clause license, not the MIT License.

## System dependencies

Python, Bash, FFmpeg, PipeWire and ALSA utilities are external system
dependencies. Their respective licenses apply to those projects.


## Desktop App runtime

The VolcaStudio XL Desktop App uses PySide6/Qt (LGPLv3/GPLv3 or commercial
terms), sounddevice and PortAudio, mido and python-rtmidi. Their upstream
licenses remain applicable; packaging must preserve dependency notices.
PyInstaller is a build tool, with its bootloader distribution exception. Qt
Widgets/Core/Gui are used; no web engine or browser runtime is required.
FFmpeg/FFprobe executables are supplied explicitly to the packager; their
licensing and source obligations depend on the selected build. No third-party
executables are checked into this repository.


## Browser App runtime

VolcaStudio XL Browser App packages contain Python, the shared VolcaStudio XL
code, the Korg SYRO converter built from `vendor/korg-syro`,
sounddevice/PortAudio, mido and python-rtmidi/RtMidi, and the FFmpeg/FFprobe
executables supplied to `tools/build_wmc.py` (Windows/Linux CI uses BtbN's LGPL
builds of FFmpeg 9.0; macOS CI uses Homebrew's FFmpeg). Their notices travel in
the package's `licenses/` folder and installed distribution metadata. The
interface is plain HTML, CSS and JavaScript written for this project, with no
third-party web libraries, fonts or assets. The Browser App uses the user's
installed Google Chrome and bundles no browser engine. The Korg SYRO SDK notice
above applies unchanged.


## Korg firmware and DataBeat OS

VolcaStudio XL contains **no Korg firmware** and no complete DataBeat OS
updater. The user downloads Korg's official *volca sample System Updater 1.42*
(`volcasample_updater_1_42.zip`) from Korg under Korg's software licence
agreement. Korg retains all rights in its firmware and documentation.

`volcastudio/data/firmware/databeat-os-1.0.patch.json` holds only DataBeat
OS's own bytes and instructions to copy bytes from the user's Korg image. No
span of 8 or more bytes of Korg's image appears in its literal data, which is
checked in every release build against Korg's updater. On the user's computer,
Studio applies it to the user's own Korg updater and checks the result. The only Korg
material Studio redistributes is the BSD-3-Clause SYRO SDK described above;
identifiers that SDK itself contains, such as the `KORG SYSTEM FILE` format
marker, are used for compatibility.

DataBeat OS is an unofficial firmware extension by
[DataBeat — Michele Ibba](https://micheledatabeat.github.io/) for the
first-generation Korg Volca Sample. **No open-source or redistribution licence
is granted for DataBeat OS** or its patch data; VolcaStudio XL's MIT License
does not apply to them. DataBeat OS is research and interoperability work; this
describes its purpose, not a legal clearance. Credit goes to **Pajen** for his
pioneering Volca firmware work (BETA7), which informed DataBeat OS's research
and design; DataBeat OS uses the Korg 1.42 image as its base. DataBeat OS and
DataBeat are not affiliated with or endorsed by Korg.

## Groove template sources

The groove catalog contains only quantized timing offsets (no audio, MIDI or
groove files) derived from the analyses credited in its `sources` records:
Grooves From Mars (MPC3000), Kit Maker (J Dilla inspired MIDI loops) and
pATCHES (D'Angelo Groove Pack), plus analytical swing grids. The names belong
to their owners and are used for attribution; no endorsement is implied.
