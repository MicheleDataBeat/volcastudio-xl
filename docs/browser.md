# VolcaStudio XL · Browser App

**Returning to Korg?** Power on with **MEMORY + PLAY**, then select
**Korg volca sample 1.42** in **Firmware**. Follow [Return to Korg firmware](return-to-korg.md).

**VolcaStudio XL Browser App** (the Browser App) is a locally installed edition of
VolcaStudio XL that opens in Google Chrome. This guide describes
**VolcaStudio XL Browser App 1.1.0**. Use it to prepare sample kits, transpose
samples, send kits, back up and restore DataBeat OS pattern banks, apply grooves
and update firmware. It runs on Windows x64, macOS on Apple silicon and Linux x86-64.

New to the Browser App? Start with the [quick start](browser-quick-start.md)
([italiano](browser-quick-start.it.md)). Use this reference for controls, storage and troubleshooting.

## Opening the workspace

Download and extract the Browser App package, then open **VolcaStudio XL Browser App**.
The included helper opens the workspace in Google Chrome and keeps your files
and device operations on your computer. No account, Python installation or
terminal is needed. The Browser App works offline once it and Chrome are installed.

Install [Google Chrome](https://www.google.com/chrome/) separately. The helper
is included with the Browser App; you do not need to start or configure it yourself.

## Install, update, uninstall

On a narrow screen, scroll tables sideways to read every column.

| | Windows 10/11 (x64) | macOS (Apple silicon) | Linux (x86-64) |
| --- | --- | --- | --- |
| Download | `VolcaStudio-XL-Browser-1.1.0-windows-x64.zip` | `VolcaStudio-XL-Browser-1.1.0-macos-arm64.zip` | `VolcaStudio-XL-Browser-1.1.0-linux-x86_64.tar.gz` |
| Install | Right-click → **Extract All**, keep the folder (e.g. in Documents) | Open the ZIP, drag **VolcaStudio XL Browser App** to **Applications** | Extract the archive, keep the folder |
| Open | Double-click **VolcaStudio XL Browser App.exe** | Open **VolcaStudio XL Browser App** in Applications | Double-click **VolcaStudio XL Browser App** (or right-click → *Run as a program*) |
| First opening | If *Windows protected your PC* appears: **More info → Run anyway** | If macOS cannot verify the developer: **System Settings → Privacy & Security → Open Anyway** | Browser App → **Connections → Add the Browser App to the applications menu** (optional) |
| Update | Replace the old folder with the new one | Replace the app in Applications | Replace the folder (and add the menu entry again if you moved it) |
| Uninstall | Delete the folder | Move the app to the Bin | Delete the folder and the menu entry's `.desktop` file in `~/.local/share/applications/` |

On Linux the menu entry is named **VolcaStudio XL Browser App**.

Replacing or deleting the application folder leaves the separate Studio data
folders in place (see **Storage, sharing and exchange**). Keep exports of kits
and banks you want to retain. The packages are unsigned: verify the download
against the release’s `SHA256SUMS`. Use the first-opening exception above only
for that copy, if you trust it; do not disable system protection globally.

Download the packages from the [VolcaStudio XL download page](https://micheledatabeat.github.io/volcastudio-xl-releases/)
or the [VolcaStudio XL releases](https://github.com/MicheleDataBeat/volcastudio-xl-releases/releases).
Each release has a `SHA256SUMS` list to verify its downloads.

The package includes the helper, Python, the Korg SYRO converter, FFmpeg and
FFprobe, PortAudio and RtMidi. It does **not** include a browser: install
[Google Chrome](https://www.google.com/chrome/).

## Starting and closing

- **One click:** opening *VolcaStudio XL Browser App* starts the helper and opens
  Chrome as an app window. You do not type an address.
- **Already running:** opening it again does not start a second helper; it opens
  a new window of the running one.
- **Close Browser App** (top right) stops the helper after asking. If an operation is
  running, cancel it first. Closing the Chrome window also ends the helper
  about a minute later (or after ten minutes without the window), unless an
  operation is still running.
- **Chrome missing:** the Browser App opens in your default browser with a notice.
  Install Chrome and open the Browser App again; other browsers are not a supported setup.
- **Old window:** a window from a closed session shows *“This window belongs to
  a closed Browser App session”*. Open VolcaStudio XL Browser App again.

## Design and motion

The Browser App uses a paper-and-ink design. Its spaces are numbered by task;
the Desktop App offers the same tasks on its own pages. **Motion** controls brief
visual celebrations and respects reduced-motion settings.

## Find a task

| Space | Desktop App page | What you do there |
| --- | --- | --- |
| **01 Gathering** | Samples | Libraries, selection, listening, workbench (draft), varispeed, key alignment, save and send a kit |
| **02 Commons** | Samples → Manage kits… | Saved kits: open to edit, open a copy, check offline, send, export/import ZIP, archive and restore |
| **03 Memory** | Patterns | Open/save/download banks, neutral reset, restore memories or the current snapshot, DataBeat OS audio backup, decode a recording |
| **04 Movement** | Grooves | Stored memories or a current snapshot, Preserve or Reset + groove, templates per part, review, save, send, inspect the catalogue |
| **05 Firmware** | Firmware | Add the Korg updater, inspect each image’s checksum and status, follow the update procedure |
| **06 Connections** | Audio output field | Transfer output, backup input, MIDI output, installation and storage checks |

### Gathering: build a sample kit

1. Choose how to make samples available:
   **Add samples…** or **Add a folder…** copies WAVs into the Browser App's library
   folder; subfolders remain groups. JSON sidecars selected with the WAVs carry their
   varispeed history. To use an existing folder without copying it, choose
   **Manage libraries…**, enter its full path and an optional name, then
   **Register folder**. The registration is shared with the Desktop App.
2. Select samples: click, **Shift**-click for a range, **Ctrl**/**⌘**-click to add
   or remove, **Shift+↑/↓**, **Ctrl/⌘+A**. Type in the filter to narrow the list.
   **All samples** searches all available libraries, kits and variants. The Browser
   App searches the folders before dividing results into pages; use **Previous page**
   and **Next page** to reach the rest. **Refresh** rereads registrations and files
   after the Desktop App or another application changes them.
3. **Enter** adds the selection to the workbench in order. Reorder with
   **Alt+↑/↓**, the ↑ ↓ buttons or drag and drop; **Delete** removes.
4. **Space** or **Listen** plays the selected sample. Choose the listening source
   and speed as described below; **Stop** ends playback.
5. The meter shows slots and seconds of the *final* audio. Over 100 samples or
   65 seconds the meter turns red and saving is refused.

The workbench is saved automatically and survives closing the Browser App. It
references files in your libraries; save a kit to keep independent sample copies.

**Manage libraries… → Unregister** removes a shared folder reference, including
one on a disconnected drive. It leaves the folder's files in place. A draft
that depends on that registration may need you to register the folder again.

### Listen to samples

Choose **Listening source**:

- **Source audio** plays the file's channels and sample rate. At **SPEED 0** it
  reads the original file; **SPEED −12/−24** plays at half or quarter speed.
- **Volca preview (mono, 31.25 kHz)** uses the mono sample conversion used for a
  kit transfer, at **SPEED 0**, **SPEED −12** or **SPEED −24**.

Enable **Autoplay selection** to listen as you select individual samples.
The Browser App remembers autoplay and the listening source separately from the
Desktop App. The waveform and pitch estimate appear under **Listening notes**. A drum,
chord or phrase may not have one reliable pitch.

Both listening modes use **Chrome's sound output**. Route Chrome to speakers
or headphones in your computer's sound settings, away from **SYNC IN**. Choosing
**Transfer output** in Connections does not change Chrome's listening output.

### Transpose samples

**Varispeed.** Select one or several workbench rows, press **J** (lower) or **K**
(raise) and type 0–99. Pitch and duration change together like tape speed
(factor 2^(s/12)). Markers such as **+12** or **−7** add up across operations and
are stored in a JSON sidecar that travels with the sample into saved kits.
In the workbench, J/K replaces the selected entries with the rendered variants.
In the library list, it replaces matching workbench entries if the source is
already included; otherwise it adds the variant. The source files are not
overwritten. Zero makes no change.

**Make ×2 variant** (**Ctrl/⌘+D** in either list) adds a version one octave higher
and half as long. It keeps the existing workbench entries. A variant already in
the workbench is selected rather than added twice. This is an additive action;
raising a selected workbench entry by 12 semitones with K replaces that entry.

### Key alignment

**Align keys…** opens *Concord*. Choose the reference sample in **Master key**,
then select the other samples to transpose (the interface calls them *slaves*).
The Browser App analyses the samples and proposes shifts to match the reference
sample’s pitch class with the nearest transposition
(−6…+5), counting earlier varispeed. When the filename note and the measured
note disagree, you must pick **Filename** or **Measured** for that row; **Accept
proposal** stays disabled until you do. Unclear samples are excluded (unchanged)
unless you shift them manually. Edit a shift in its row, or select rows
(click, Ctrl/Shift) and use **Set shift** / **Use automatic**. The summary shows
the kit duration before → after. **Accept proposal** renders the proposal and then
replaces the workbench; **Cancel** leaves it untouched. This matches a pitch class,
not a major/minor key, chord progression or melody. Listen to the result before saving.
See [varispeed and key alignment](tuning.md) for the pitch rules.

### Save and send a kit

**Save as new kit** (Ctrl/⌘+S) writes independent copies with their metadata.
A kit opened from Commons can be **replaced**; its previous version is archived.
**Check signals offline** encodes and verifies every SYRO signal and discards
them; it plays nothing.

**Sending clears all 100 sample slots on the Volca before loading the kit.**
Keep the audio needed to reload anything you want to preserve; pattern backups
cannot recover sample audio.

Choose **Send saved kit to Volca…** to prepare the signals and read the summary.
Confirm with **Clear & send** only when ready. Cancel is selected by default.
After **Signals sent**, check the samples on the Volca.

### Download prepared kit signals

**The clear and upload WAVs are data signals. Do not listen to them through
speakers or headphones. Playing a kit's clear signals to SYNC IN erases all
100 sample slots.** Keep any sample audio you need to reload.

Save the kit, then choose **Download SYRO files…** and **Prepare download**.
The Browser App downloads a ZIP containing the clear/upload WAVs, normalized sample
copies and a manifest. It uses the shared SYRO encoder and sends nothing to the Volca.
This is separate from **Export ZIP**, which copies a kit for opening in Studio,
and from **Check signals offline**, which does not keep the signals.

### Commons: manage saved kits

Lists Studio kits and existing packs with slots, seconds and memory use.
**Export ZIP** saves a kit's files byte for byte (WAVs, sidecars, notes) as
`name.volcakit.zip`; **Import kit ZIP** creates a new kit from such a file, also
from a ZIP of a kit folder made by hand. **Move to archive** is recoverable from
the list below; restoring never overwrites a kit with the same name.

### Memory: back up patterns

Backups contain ten pattern memories and a separate current-edit snapshot. They
do not contain sample audio or all GLOBAL settings. DataBeat OS 1.0 is required.

1. Connect a computer USB-MIDI output to the Volca’s **MIDI IN** and the Volca’s
   **headphone** output to a computer audio input.
2. In **Connections**, choose **Backup input** and **MIDI output**. Disable input
   effects, noise suppression and automatic gain. Allow the local helper to
   record if the operating system asks.
3. In **Memory**, enter a name and choose **Capture backup**. Read *Capture a
   pattern backup?* and choose **Start capture**. The Volca stops playback for
   the export; leave its controls untouched for about two minutes.
4. Wait for the complete bank: ten memories and the current snapshot. An
   incomplete or corrupt recording does not produce a saved bank.

**Decode a recording…** reads a complete recording of a previous DataBeat OS
export; it does not request another export. **Download copy** saves an unchanged
`.vspatterns` file for another computer. Each bank save needs a new name.
See [audio pattern backup](pattern-audio.md) for the signal format.

### Memory: restore or create patterns

**Restoring replaces the selected pattern memories.** Later edits on the Volca
that are absent from the bank will be lost. Sample audio and GLOBAL settings
are untouched.

1. Open a saved bank or choose **Open a file…**. **Destination firmware** shows
   **DataBeat OS 1.0 pattern format**, the format of DataBeat OS 1.0 on the Volca.
   This choice does not install firmware. Memories in another format remain in
   the bank byte for byte and cannot be selected for restore.
2. Tick the memories to replace (**All compatible** ticks every restorable
   memory) and choose **Restore selected memories…**.
3. Review the destinations and chosen SYNC IN output, then confirm. After
   **Signals sent**, select a restored memory on the Volca and check it.

The current snapshot stays in the file unless you choose **Restore snapshot…**
and an explicit destination. **Create neutral patterns** prepares empty
patterns in the DataBeat OS 1.0 pattern format offline; it sends nothing until
you restore them. *Also reset the current edit buffer through MIDI* is optional
and is available only for these neutral patterns. **That option discards unsaved
edits in the Volca's live edit buffer**, after replacing the selected stored memories.

**Do not audition pattern SYRO WAVs through speakers or headphones. Playing
them to SYNC IN replaces the specified stored memories.**

To keep prepared pattern signals, tick the stored memories and choose
**Download selected SYRO files…**. For the separate current snapshot, choose
**Current snapshot to memory** (1–10), then **Download snapshot SYRO…**. Both
actions download a ZIP with the pattern data, SYRO WAVs and manifest, without
playing anything. The downloaded files do not perform the optional MIDI reset
of the live edit buffer. See [pattern banks](patterns.md) for the managed archive.

### Movement: apply grooves

The groove editor works on DataBeat OS 1.0 patterns and changes only their
microtiming bytes.

1. Choose **Pattern source → Stored memories**, then tick memories or choose
   **All 10 patterns**. To use the bank's separate current snapshot instead,
   choose **Current snapshot from the loaded bank** and one **Destination memory**
   (1–10). This maps that snapshot to a stored memory; it does not load the
   Volca's live edit buffer.
2. Choose **Preserve** to change timing in an existing bank, or **Reset + groove**
   to begin with empty patterns. For stored memories, Preserve needs a loaded
   copy of each selection. For a current snapshot, it uses that snapshot's notes,
   Predictability, motion and other settings.
3. Choose a template per part. **Review change plan** shows destinations,
   assignments and whether the source contains their originals, without saving
   or sending. Enter a new bank name and choose **Apply templates & save bank**.
4. To replace those memories on the Volca, choose **Send saved groove bank to Volca…**
   and review the confirmation. Changing the plan disables Send until you save again.

Templates change microtiming: small advances or delays relative to the step
grid. They do not add sample audio. Use **SWING 0** as the reference when
comparing templates; the instrument’s swing adds to them.

The new bank contains only the selected destinations. When a source bank was
loaded, the Browser App also saves a complete `.rollback.vspatterns` copy, including
its separate current snapshot. This is the source you opened, not a new backup of
the instrument. If it lacked a destination memory, the Browser App says that memory
has no original copy. Reset without a source creates no rollback file. Reopen the
original or rollback bank to make another edit from its current snapshot.
After saving, the Browser App opens the output bank and switches **Pattern source**
back to **Stored memories**. See [groove templates](grooves.md).

### Inspect a groove

In **Groove catalogue**, choose a **Category** or search by profile/source name.
**Timing profile** groups aliases that produce the same sixteen offsets.
Choose **Source / instrument / bar** to inspect a particular alias; aliases can
share timing while retaining different source measurements.

The table gives each step's exact integer microtiming and identifies it as
**measured**, **reconstructed** or **analytic**. The provenance below includes
the source, source checksums and unrounded timing fractions. The catalogue has
217 distinct profiles and 270 named templates. Choose **Use for part** (1–10),
then **Use this template** to fill that part's assignment. Review the plan and
save the bank to apply it; browsing the catalogue alone changes no pattern data.

### Firmware: update the Volca

Studio contains no firmware. Download Korg's official **volca sample System
Updater 1.42** (`volcasample_updater_1_42.zip`) from Korg's
[volca sample download page](https://www.korg.com/us/support/download/software/0/370/1475/),
then choose **Choose the Korg 1.42 updater…** in **Firmware**. Choose the zip
unchanged, or the `volcasample_sys_0142.wav` inside it. The Browser App builds
**DataBeat OS 1.0** on this computer and checks the result. The archive then lists
two entries: **DataBeat OS 1.0** and **Korg volca sample 1.42** (to return to
Korg's firmware). Select an entry to see its status, SHA-256, duration and
provenance, then choose **Begin update…** to review the procedure. Installing
Studio alone does not update the Volca. See the [firmware guide](firmware.md)
and, for the instrument's features, the [DataBeat OS manual](databeat-os-manual.md).

Before sending, connect the chosen computer output directly to **SYNC IN**,
disconnect speakers and headphones from that output, stop other computer audio
and disable audio processing. Use reliable power. To install DataBeat OS, use
**FUNC + PLAY → UPdt** at startup. To return to Korg 1.42 from DataBeat OS, use
**MEMORY + PLAY** (forced update, final display dot lit), then release the
buttons. Keep a backup of your DataBeat OS patterns. The confirmation lists each
step; **Cancel — keep the Volca as it is** is selected by default. Choose
**Send firmware signal** only when the Volca is ready. Do not interrupt the signal
or switch off the instrument. Wait for **End** on the Volca, then restart and check
its version by powering on while holding **REC**. At startup, DataBeat OS 1.0
scrolls `dAtAbEAt OS` on the display. **Signals sent** confirms computer playback,
not successful installation.

Firmware signals are sent unchanged and are never auditioned. If an update is
interrupted, consult the [firmware guide](firmware.md) rather than following a
sample-transfer retry.

## Connections, cables and MIDI

Choose devices by name in **Connections**. The Browser App remembers them in its
own settings (the Desktop App's device choices are separate and unchanged). If a
saved device is not connected, operations stop with a message; the Browser App
never falls back to the system default. Press **Refresh devices** after plugging
an interface in. While your computer's shared audio output is available (PipeWire
or PulseAudio on Linux), outputs that would take the sound card for themselves are
kept out of the list, so a transfer never leaves Chrome or your music software silent.

**Check installation** lists the installed tools and Studio folders without
opening audio or MIDI devices. Use the displayed paths when locating libraries,
kits, banks or settings; this check does not test the Volca or its connections.

| Purpose | Cable | Choose in Connections |
| --- | --- | --- |
| Samples, patterns, grooves, firmware | Computer audio output → Volca **SYNC IN** | Transfer output |
| Pattern backup | Volca **headphone** output → computer audio input | Backup input |
| Pattern backup, optional current-buffer reset | USB-MIDI interface → Volca **MIDI IN** | MIDI output |

Before sending, disconnect speakers and headphones from the transfer output:
firmware and SYRO WAVs are data signals. Pause other audio and notifications.
Turn off EQ, "enhancements" and spatial audio on that output. Avoid distortion.
The SYNC IN connection carries no acknowledgement back to Studio; confirm
receipt on the Volca.

**What needs MIDI.** Audio pattern backup uses a MIDI output connected to the
Volca's MIDI IN to request the export. Resetting the current edit buffer through
MIDI is optional. Kits, pattern restores, grooves, neutral stored-pattern resets
and firmware updates use audio. **Decode a recording…** turns an existing
complete recording of a DataBeat OS export into a bank; it does not start a backup.

## Storage, sharing and exchange

The Browser App shares registered libraries, saved kits, pattern banks and firmware
with the Desktop App on the same computer. The Browser App’s workbench draft,
autoplay, listening source and device choices are separate.
Replacing or deleting the application does not remove these separate folders.

Default locations are defined by Studio’s configuration; environment overrides
and `config.json` can change them.

| System | Configuration | Data and state | Cache |
| --- | --- | --- | --- |
| Linux | `~/.config/volcastudio/` | Data: `~/.local/share/volcastudio/`; state: `~/.local/state/volcastudio/` | `~/.cache/volcastudio/` |
| macOS | `~/Library/Application Support/volcastudio/` | `~/Library/Application Support/volcastudio/` | `~/Library/Caches/volcastudio/` |
| Windows | `%APPDATA%/volcastudio/` | `%LOCALAPPDATA%/volcastudio/` | `%LOCALAPPDATA%/volcastudio/` |

Saved kits are under `kits/`, banks under `patterns/` and firmware under
`firmware/` in the data folder. The Browser App keeps its own files in a separate
subfolder of the data, state and cache folders: imported sample copies and copied
firmware provenance in data; the workbench (`draft.json`) and preferences
(`settings.json`) in state; listening previews and prepared download files in
cache. The **Guide** space shows the folder that holds the Browser App's sample
copies. Keep the downloaded ZIP when you need those signals later; its
helper download link belongs to the current session. Where the OS shares data,
state and cache roots, these subfolders still serve different purposes.
Do not delete the whole root as a way to clear previews.

- Kits saved in the Browser App also appear in the Desktop App. **Manage libraries…**
  edits the same registrations used by the Desktop App; registered audio is read in place.
- **Remove copy** deletes the Browser App’s imported copy of a folder. Keep anything
  you need before choosing it. It does not delete the original folder you imported
  or a registered library read in place.
- To move kits between computers, use **Export ZIP / Import kit ZIP** in
  **Commons**. Use **Download copy** and **Open a file…** for pattern banks.
  These exports contain independent copies; device choices and the unsaved
  workbench are not included. Register external libraries again on the new
  computer, where their paths may differ.

## Chrome and platforms

- **Chrome** (current stable) is the supported browser. The page uses file pickers
  for imports; audio and MIDI devices are handled by the local helper, which may
  need operating-system permissions. The page does not request browser microphone,
  Web MIDI or persistent file-system access.
- **Windows** lists the same interface once per audio system (MME, DirectSound,
  WASAPI…). Prefer the WASAPI or MME entry of the interface wired to SYNC IN.
- **macOS** asks for microphone access the first time you capture a backup.
  If you refuse, the backup stops with instructions; allow *VolcaStudio XL Browser App*
  in **System Settings → Privacy & Security → Microphone**.
- **Linux** uses the desktop's ALSA/PipeWire. PipeWire may resample if the
  device runs at another rate, as with the Desktop App.

## Your files and transfers

- The Browser App’s helper listens on this computer’s loopback address and checks
  a session token and request origin. Keep the private session link to yourself.
- Only one transfer can run at a time across the Browser App and the Desktop App.

## Troubleshooting

| You see | Do this |
| --- | --- |
| *Choose the audio output connected to SYNC IN* | Connections → Transfer output |
| *… is not connected* | Reconnect the interface, press Refresh devices, or choose another device |
| *No audio outputs found* | Connect the interface or adapter, then Refresh devices |
| *MIDI is unavailable* | Connect the USB-MIDI interface; on Linux make sure ALSA MIDI is available; Refresh |
| *The audio input could not be opened…* | Grant microphone access (macOS/Windows privacy settings), check the cable, Refresh |
| *Another operation is in progress* | Wait or press Cancel at the bottom |
| *This window belongs to a closed Browser App session* | Open VolcaStudio XL Browser App again |
| Over budget (red meter) | Remove samples or shorten them with varispeed up |
| *Stopped while sending* | For a kit, some slots may be cleared or loaded; check the connection before resending the full kit. For patterns, inspect the affected memories. For firmware, consult the [firmware guide](firmware.md) before further action |
| Chrome does not open | Open VolcaStudio XL Browser App again; install Chrome if the notice says it is missing |
| A registered folder is unavailable | Reconnect its drive and press **Refresh**, or use **Manage libraries… → Unregister** to remove its reference |
| Listening comes from the wrong speakers | Choose Chrome's output in the computer's sound settings; **Transfer output** controls sends only |

## Credits and help

A [DataBeat](https://micheledatabeat.github.io/) project by Michele Ibba.
See the [download page](https://micheledatabeat.github.io/volcastudio-xl-releases/)
for both editions and the [quick start](browser-quick-start.md) for the first kit.
