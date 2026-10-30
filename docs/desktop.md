# VolcaStudio XL Desktop App

This guide describes **VolcaStudio XL Desktop App 1.1.0**, the native desktop
app of VolcaStudio XL. It shares saved kits, libraries, banks, firmware and the
musical backend with the [Browser App](browser.md) (Chrome). Each app has its
own controls and draft selection.

The window header reads **VOLCASTUDIO XL / DESKTOP APP — Kits, patterns,
grooves, firmware**. Choose a section with the mouse or keyboard. Tab moves
focus; Ctrl+S saves the current kit; Ctrl+O opens a pattern bank. The window
opens no larger than the screen, can be resized down to 640 × 480 (half of a
1280 × 720 desktop) and keeps its controls at their natural size; sections
scroll when needed.

## Sections

- **01 / Samples:** two panels, like the Browser App. On the left you browse your
  libraries and saved kits: search, **Preview selected sample**, and **Add to
  kit** (or press Enter). On the right you build the kit: add WAV files, put
  the samples in slot order, remove them, preview them at the original pitch or
  at SPEED −12/−24, change their pitch, make ×2 variants, align keys and save.
  Reopen a saved kit with **Open saved kit…**; **Save changes** updates it,
  **Save independent kit** keeps a separate copy. The **Listening notes** under
  the panels follow whichever sample you select: its waveform, how long it is
  and how much of the Volca's memory it takes, its format, the note the Desktop
  App hears in it and how sure it is, the notes you would get at SPEED −12 and
  −24, and where it comes from if it was already transposed. In a narrow window
  the two panels stack, kit first. Sending replaces the instrument's sample
  memory and asks for a separate confirmation after encoding.
- **02 / Patterns:** open a bank, save a copy, create neutral patterns, restore
  selected memories, or capture an optional pattern backup with **Capture
  pattern backup…** through MIDI OUT and audio IN on the computer. Backup is not
  a prerequisite for reset or restore. The Patterns selector shows the
  **DataBeat OS 1.0 pattern format**, the format of DataBeat OS 1.0. Memories in
  another format stay in the bank; they are not sent. **Select compatible
  memories** selects the stored memories that can be restored. A
  current-buffer-only snapshot needs its own destination memory.
  See [pattern banks](patterns.md).
- **03 / Grooves:** tick one or several pattern memories (or use
  **All 10 patterns**), then choose a template per part. The same assignments
  apply to every selected memory. Memory selections stay synchronized with
  Patterns, and the templates target the DataBeat OS 1.0 pattern format. Search
  the template dropdowns by name. Preserve mode needs a local copy of every
  selected memory; reset + groove needs no bank or backup.
  **3 / Apply templates & save bank…** creates a new file offline. Then choose
  an audio output and **4 / Send saved groove bank to Volca…** to prepare the
  transfer and review a separate confirmation. Restoring complete patterns can
  replace edits made since the source copy. Changing selections disables Send
  until you save again. See the
  [one/several/all walkthrough](grooves.md#desktop-app-on-linux-windows-and-macos).
- **04 / Firmware:** VolcaStudio XL contains no firmware. Download Korg's
  official `volcasample_updater_1_42.zip` from Korg's
  [volca sample download page](https://www.korg.com/us/support/download/software/0/370/1475/)
  and choose **Add Korg 1.42 updater…**. The Desktop App builds
  **DataBeat OS 1.0** from it on your computer, checks the result and keeps the
  Korg updater. The list shows **DataBeat OS 1.0** and **Korg volca sample
  1.42**, for restoring Korg's firmware. Select one, then **Begin
  update…**. See the [firmware guide](firmware.md) and the
  [DataBeat OS manual](databeat-os-manual.md).

Choose **Audio output** before previewing or sending. The Desktop App uses that
output for both: do not preview samples through an output connected to
**SYNC IN**. The list offers only outputs that can play the transfer signal,
and puts the normal choice first: on Linux **System audio via PipeWire** or
**System default output**, which share the sound card with your other programs.
Outputs that would take the card for themselves and leave Chrome or your music
software silent are kept out of the list while a shared one exists; on a
computer with no sound server at all, they appear on their own. If you really
need a direct hardware output, start the Desktop App with
`VOLCASTUDIO_EXCLUSIVE_OUTPUTS=1`. Outputs that only work at another sample
rate are left out as well, and if an output cannot be opened, the message says
what to choose instead.
The Desktop App remembers its own audio input, output and MIDI choices by name.
A missing or ambiguous device requires you to select one again; refresh does
not choose a replacement. These choices are separate from the Browser App.

Device actions run in
background workers; the window remains responsive. The final confirmation shows
prepared-transfer details and defaults to Cancel. Cancellation stops remaining
work; it cannot undo portions already delivered to the instrument. Completion
means signals were sent, not that the Volca acknowledged them.

Firmware updates follow the instrument procedure shown in the confirmation
before sending: the connection, the buttons to hold at power-on and how to
check completion on the Volca.

## Install

Download the package for your computer from the
[download page](https://micheledatabeat.github.io/volcastudio-xl-releases/),
extract it and open **VolcaStudio XL Desktop App**. On macOS, move the app to
**Applications**. Packages support Windows 10/11 x64, macOS on Apple silicon
and Linux x86-64 with glibc 2.35 or later.

The packages are not code-signed. Verify the download against the release’s
`SHA256SUMS` before opening. For a copy you trust, Windows offers
**More info → Run anyway**; macOS offers
**System Settings → Privacy & Security → Open Anyway**. Use an exception for
that application, without disabling system protection.
When recording an audio backup on macOS, allow the app to use the microphone.
Updating the Desktop App keeps your Studio library and settings.

**04 / Firmware** accepts only the official Korg 1.42 updater, as downloaded
(zip) or the `volcasample_sys_0142.wav` inside it; any other file is refused
and nothing is saved. It offers only DataBeat OS 1.0 and Korg volca sample 1.42.
Every transfer shows a separate confirmation first.

## Reopen, edit and send a kit

**Sending clears all 100 sample slots on the Volca before loading the kit.**
Read the transfer confirmation before approving it. Saving or checking signals
on the computer does not update the instrument.

Connect the chosen output to **SYNC IN** and disconnect speakers and headphones
from it. Stop other audio on that output.

1. In **Samples**, choose **Open saved kit…** (Ctrl+Shift+O). Select the kit’s
   folder inside Studio’s `kits` directory or your configured existing packs.
   The Desktop App loads all WAVs in the slot order the Browser App uses.
2. To send that kit unchanged, choose an **Audio output**, then **Send saved kit…**.
   You do not need to save another copy first. **Check signals offline** encodes
   and verifies the signals without opening an audio device or sending anything.
3. To edit the kit, add or remove samples, change their order or transpose them.
   The Desktop App disables checking and sending until you save those changes.
4. At the top of **Samples**, choose **Save changes** to replace the opened kit. Confirm the replacement;
   Studio archives the previous version first. To keep a separate kit instead,
   enter a new name and choose **Save independent kit**.

For a new selection, enter a kit name at the top of **Samples**, then choose
**Save independent kit**. **Ctrl+S** saves changes to an opened kit, or asks for
a name when creating a new one. The save controls are visible without scrolling
at 800 × 600 and larger window sizes.

**New kit** starts a new selection. Opening another kit or starting a new one
asks before discarding unsaved changes. Saving changes is blocked while another
Studio transfer is active. If the Browser App changes an opened kit, reopen it
before saving, checking or sending.

## Resume a selection

The Desktop App saves its sample selection, order and kit name as you work, and
reopens that draft on the next start. A draft refers to existing files; it does
not copy or back up their audio. Save a kit to keep independent sample copies.

If files are missing or an opened kit changed in the Browser App, the Desktop
App reports the problem and keeps the draft. Reconnect the source drive or
restore the missing files, then use **Recover draft…** to select the draft JSON.
If you start new work before recovering it, the old record is kept in the
`recovery` folder shown by that dialog. For a changed saved kit, reopen the kit
explicitly.

## Browse a library

1. The left panel of **Samples** lists registered libraries and kits. Choose one
   from the menu, or **Browse folder…** for another folder.
2. Type in the search field. Select a sample: the **Listening notes** below the
   panels show its waveform and a pitch estimate without playing audio. Drums,
   chords and phrases may not have a reliable single pitch.
3. **Preview selected sample** plays it, or enable **Preview on selection**.
   First choose an output connected to speakers or headphones, away from the
   Volca's **SYNC IN**.
4. Select one or several samples and choose **Add to kit** (or press Enter).
   They join the kit on the right; save the kit when ready.

**Register library…** adds a folder to Studio's shared library list.
**Unregister** removes its registration and leaves its files in place.

## Archive or restore a kit

Save pending kit changes first, then choose **Manage kits…**. Select a saved
kit and **Open selected kit** to edit it. **Move to archive…** removes that kit
from the saved list and keeps it in Studio's archive after confirmation.

To recover a previous version, select it in the archive list and choose
**Restore selected version…**. Restoration stops if its original directory
already exists. Save the current kit under a separate name and archive the
conflicting kit before restoring the older version. Source libraries are not
moved by these kit actions.

## Restore a snapshot or reset patterns

**These actions replace patterns on the Volca. Back up any patterns you want
to keep. A pattern backup does not include sample audio or all GLOBAL settings.**

To store a bank's current edit-buffer snapshot, open that bank in **Patterns**,
choose **Restore current snapshot…**, then choose a destination memory from
1 to 10. Choose **Audio output** connected to **SYNC IN** and review the transfer
confirmation. Only that stored memory is replaced. Select it on the Volca
afterwards; this action does not directly load the live edit buffer.

To clear patterns, enter the memories to clear, then choose **Reset memories +
current buffer…**. This also replaces unsaved edits in the Volca's current
buffer, so choose **Select MIDI output** and a port connected to **MIDI IN** first. Stored memories
are sent through **SYNC IN**, followed by the current-buffer reset over MIDI.
Review both scopes in the confirmation before sending. Sample audio is retained.

**Signals sent** confirms computer playback only. Check the selected pattern
memories and current buffer on the Volca after the transfer.

## Decode an existing pattern backup

In **Patterns**, choose **Decode recorded backup…**, select a recorded pattern
backup WAV, then choose a new bank filename. The Desktop App saves and opens the
ten memories and current snapshot only when all eleven frames pass validation.
It does not record or send anything. Existing bank files are not replaced.
Cancelling waits for decoding of the current file to finish and prevents saving
the result.

## Tune and align samples

Select one or several sample rows, then Lower/Raise (J/K) and enter up to two
digits. **Align kit keys…** opens the **Pitch alignment** window and waits for
you: choose the master sample, tick the samples you want to bring to its key
(rows already selected in Samples come ticked) and press **Align selected**.
Only those samples are listened to and transposed; you can pick between the
note in the file name and the note the Desktop App hears, set your own shift
for one or several rows, and see which samples were left alone because their
pitch is unclear, plus the new kit length. **Accept aligned kit** puts the
result in the kit; saving and sending stay separate steps. See [tuning](tuning.md).
