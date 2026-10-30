# Pattern banks

VolcaStudio XL targets first-generation Volca Sample running **DataBeat OS 1.0**.
The Desktop App and the Browser App share lossless pattern archives and use one
pattern format, the **DataBeat OS 1.0 pattern format**. Sample kits and GLOBAL
settings remain separate from pattern banks.

Edits on the Volca change the pattern currently in use. WRITE saves that
whole pattern to a memory for later recall; it is not required after each
change. A complete audio backup keeps both the stored memories and a separate
snapshot of the current pattern, including edits not saved with WRITE.

The DataBeat OS 1.0 pattern format stores Predictability ALL + P.01–P.23 and
eight independent bar choices per part. Studio inspects, backs up, restores and
resets patterns in this format, and the [groove editor](grooves.md) changes
their microtiming. Studio does not convert banks between formats. See the
[DataBeat OS manual](databeat-os-manual.md) for what each setting does on the
instrument.

## Inspect, restore and reset

**Restoring a bank replaces the stored memories listed in it. A reset clears
notes and motion in all ten stored memories.**
Back up any patterns you want to keep before sending either operation. Neither
operation backs up or changes sample audio. Inspection does not send anything.

The destination selector offers the **DataBeat OS 1.0 pattern format**: the
Desktop App shows it in the Patterns selector, the Browser App in
**Memory → Destination firmware**. Selecting it does not install firmware or
change the loaded bank.
Restores use SYRO through the chosen output → SYNC IN.
All signals are encoded before the confirmation. Only the displayed stored
memories are replaced; sample audio is untouched. Select a restored memory on
the instrument afterwards. Completed playback reports signals sent, not receipt.

Reset creates ten empty patterns in the DataBeat OS 1.0 pattern format:
notes/motion cleared, Predictability ALL, all eight bars admitted, microtiming
zero, echo off, ratchet one, slicing off, scales chromatic and intra-bar loop
OFF. Ordinary controls return to native defaults.
Backup is optional. A reset can also replace the volatile current buffer
through MIDI after stored transfers; otherwise select a cleared memory to
replace the unsaved edit buffer. Studio cannot read which firmware is
installed: audio playback is one-way, so make sure the Volca runs DataBeat OS
1.0 before restoring or resetting.

A bank may retain ten stored memories plus an extra current snapshot. Restore
normally leaves that snapshot in the file. Current-only raw/SysEx imports
require an explicit destination. Uninitialized/opaque saved slots retain their
original bytes. Native patterns without extensions are validated and restored
unchanged. Original bank files are never overwritten.

## Banks in another format

Studio does not convert banks. A memory in another extension format stays in
the bank byte for byte, but it is not compatible with the DataBeat OS 1.0
pattern format and is not restored: Studio refuses it for editing and transfer
rather than reinterpreting it. **Select compatible memories** (Desktop App) and
**All compatible** (Browser App) leave such memories out. Installing firmware
does not convert stored memories either. Keep your original backups.

## Audio backup

The original MIDI IN is sufficient with DataBeat OS: connect the computer's MIDI
output → Volca MIDI IN, and Volca headphone output → computer audio input.
Choose an unprocessed input without automatic gain, noise suppression or effects.
In the Desktop App, choose **Capture pattern backup…** in Patterns. In the
Browser App, choose **Capture backup** in Memory and confirm **Capture a pattern
backup?**.

Backup stops playback and temporarily suspends edits. Keep controls untouched
for approximately two minutes. Only eleven complete, CRC-valid frames publish
a bank; interruption or corruption does not save a partial result.

New managed imports and backups get a name that starts with the format of their
contents (for example `mixed-`, `native-` or `opaque-`), followed by the source
name and timestamp. Existing files remain where they are; listing and inspection
derive format labels from their payloads. Explicit output filenames are
respected and never overwritten.

A backup can contain memories in the DataBeat OS 1.0 pattern format, native,
opaque and other-format stored slots together, plus a current snapshot. This is
accepted and preserved in one complete archive. It is different from mixing
frames from separate capture sessions, which is rejected. Each app offers the
compatible memories for the destination and keeps incompatible memories in the
archive. A current snapshot still requires an explicit destination memory; it
is not implicitly restored with stored memories. Archives saved with an older
label for this format open without changing their payloads.

Every pattern is exactly 2624 bytes. No reconstruction of motion or
Predictability occurs during backup transport. See
[audio protocol](pattern-audio.md).

## Audio devices and operation boundaries

The Desktop App chooses native named devices. Disconnected selections block
instead of falling back to a default. Transfers share one lock and require
confirmation; cancellation stops remaining work, while previously delivered
memories may already have changed. PipeWire force-rate is restored and
force-quantum retained.
