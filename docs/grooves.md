# Groove templates

The groove editor targets the **DataBeat OS 1.0 pattern format** in the Desktop
App and the Browser App. The catalog ships with both apps and is shared with
the community under the MIT License (only quantized timing values; no audio,
MIDI or groove files). It offers 217 timing profiles and 270 named
source/instrument/bar aliases: MPC3000, coordinated Dilla instrument grids,
analytical straight/quintuple/sextuple/septuple swing, and two D'Angelo
selections. Source fractions, family identities and measured/reconstructed
positions remain available in each template's provenance.

Templates use −15…+15 microsteps, each 1/32 of a step. Reference **SWING 0**;
instrument swing adds to the template. Editing microtiming on the instrument
subsequently edits the groove. No extra firmware effect or DSP is involved.

## Preserve or reset + groove

**Preserve** changes only the sixteen microtiming values and their valid bits in
assigned parts. Notes, sample IDs, all Predictability selections, packed motion,
bar filtering, echo, ratchet, slicing, loop, scales and other data remain intact.
It requires a local copy of every selected memory. A new backup is optional.

A native (stock) pattern takes the DataBeat OS 1.0 pattern format exactly when
it is saved with a groove; apart from the format itself, only its timing bytes
change. A memory in another
extension format is refused: grooves never convert formats.

**Reset + groove** starts with neutral empty patterns in the DataBeat OS 1.0
pattern format, then applies the chosen templates. It needs no bank or backup.
If originals are available, the rollback file retains only actual source data;
missing memories are not represented as invented backups.

A memory is a stored pattern (1–10); a part is its sample channel (1–10).
The same part/template assignments apply to every selected memory. Repeat an
operation with a different selection to give different memories different grids.

## Send a groove bank

**Sending replaces the selected pattern memories.** A bank saved earlier may
replace later edits on the instrument. Back up those edits first if you want
to keep them. Saving a bank on the computer does not change the Volca.

## Desktop App on Linux, Windows and macOS

1. Open **03 / Grooves**; open a pattern bank for preserve, or check Reset + groove.
2. Choose memory checkboxes: **Clear selection** then one/several, or **All 10 patterns**.
3. Assign templates to parts and click **3 / Apply templates & save bank…**.
4. Choose the audio output connected to SYNC IN, then **4 / Send saved groove
   bank to Volca…** and confirm the displayed memories.

Saving alone does not change the instrument. Changing the plan invalidates its
saved send selection; save again. Reopen the original full source bank before
preserving memories absent from a previously saved subset.

The application cannot retrieve pattern data through SYNC IN.
