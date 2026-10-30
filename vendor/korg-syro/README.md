# Korg SYRO SDK

This directory contains the unmodified source files needed to generate sample,
erase and pattern transfer signals from the official Korg SYRO SDK. It contains
no precompiled executables, factory samples or preset patterns.

Upstream: https://github.com/korginc/volcasample  
Revision: `b0ed615f18c230a18b378d9ddc6a936971597e4e`

The SDK and its command-line example are distributed under the BSD 3-Clause
license in [COPYING](COPYING). File checksums and provenance are recorded in
[PROVENANCE.json](PROVENANCE.json).

Build the backend from the repository root:

```sh
python3 tools/build_syro.py
```

The build uses C99 for compatibility with the SDK's original Boolean type
definitions. VolcaStudio XL normalizes sample inputs to PCM16 mono before calling
the backend; transfer signals are PCM16 stereo at 44.1 kHz.
