# Varispeed and key alignment

Varispeed changes pitch and duration together, like tape speed. A shift of `s`
semitones multiplies playback speed by `2^(s/12)` and divides duration by that
factor. Saved kits retain transformed audio and metadata
recording the cumulative shift, including changes made before key alignment.

## Choose semitones

**Desktop App → 01 / Samples:** select one or more kit rows and use **Lower pitch… (J)**
or **Raise pitch… (K)**. Shortcuts work while the sample list has focus. Ctrl/Shift
selection applies the entered value to several samples together.

The direction sets the sign; enter only `0`–`99`. Zero leaves audio unchanged.
A second operation adds to the total displayed beside the sample. J + `07`
marks **−7**, speed ×0.6674, duration ×1.4983; K + `24` marks **+24**, speed ×4,
duration ÷4. The kit meter measures the transformed audio. A single sample over
65 seconds is refused; a saved kit must fit within 100 slots and 65 seconds.

## Align a completed kit

Open **Align kit keys…** in the Desktop App. Alignment is optional and works offline. The Desktop App does nothing until
you ask: choose the master, tick the samples to align and press
**Align selected**. Only the master and the ticked samples are listened to and
transposed; rows already selected in Samples come ticked.

1. Choose a reference sample in **Master key**, then tick the other samples
   to transpose. The reference sample stays unchanged. **All slaves** and
   **No slaves** help with large kits.
2. Press **Align selected**. Filename notes are compared with measured audio
   notes; both include prior varispeed. When they disagree, explicitly choose
   **Filename** or **Measured** for that sample and press **Align selected**
   again. Nothing is rendered until relevant discrepancies are resolved.
3. Review additional shifts, cumulative semitones and the resulting duration.
   Automatic shifts match the reference sample’s **pitch class**, using the nearest
   transposition within −6…+5 semitones. This keeps the existing register as far
   as the nearest choice allows. It does not convert major/minor modes or
   reharmonize chords and phrases.
4. Edit individual shifts or apply one manual amount to several selected samples
   together, then press **Align selected** again. Manual amounts explicitly
   bypass pitch inference for those samples. You can return to automatic
   calculation. Over-budget results are not rendered until adjusted.
5. **Accept aligned kit** replaces the draft only with complete outputs whose
   measured total fits. **Cancel** leaves it intact. Save normally afterwards;
   transfer remains a separate confirmation.

Samples with neither a clear filename note nor a reliable monophonic estimate
are listed as excluded and kept unchanged. They remain available for manual
varispeed. An excluded sample does not block the others; an unclear reference sample does.
The estimator is not musical-key or chord detection. Drum transients, polyphony
and changing melodies may be uncertain even when a filename contains a note.

Filename recognition accepts distinct tokens such as `F#3`, `Bb`, `Cmin` and
`D_major`. Multiple different note tokens are ambiguous. Wrong filename labels
and octave errors in measured pitch remain possible; both sources are visible.
Pitch confidence is an estimate, not a guarantee. A `?` beside a shift means
older transformation history cannot be fully recovered (for example, a missing
parent file). Filename-based inference is disabled for that uncertain history;
actual audio can still supply a measured note.

Slot order, unselected samples and source libraries remain intact. Completed
variants may remain available if a later render fails or is cancelled; they do
not enter the draft unless the complete operation succeeds.
