# DataBeat OS 1.0 — manual

For the **first-generation Korg volca sample**. At startup the display scrolls
**dAtAbEAt OS**.

DataBeat OS offers Predictability with 24 choices, eight independent bars in the
bar filter, vinyl stop on LIVE pads 8–11, and visible notes in PrEd and Time.
Inside LIVE you can also set the loop and choose patterns without leaving the page.
It uses the DataBeat OS 1.0 pattern format; see
[patterns and Studio](#patterns-and-studio).

VolcaStudio XL contains no firmware. It builds DataBeat OS 1.0 on your computer
from your own Korg volca sample System Updater 1.42, checks the result and
transfers it to the Volca through SYNC IN. See the
[Studio firmware guide](firmware.md) for the procedure.

A [DataBeat](https://micheledatabeat.github.io/) project, not affiliated with Korg.

**Returning to Korg?** Power on with **MEMORY + PLAY**, then send the
original Korg updater from Studio. See [Return to Korg firmware](return-to-korg.md).

## Editing and saving

**Your edits change the pattern currently in use.** You can keep playing,
leave an extension page and return without pressing WRITE. Changes follow the
timing of the notes and effects they control. Notes already prepared for
playback may keep their previous settings; loop changes follow the boundary
rules described below.

**WRITE saves the whole pattern to a memory, as on the standard Volca Sample.**
It is not an Apply button for the extra functions. Use it when you want to
keep the pattern for later recall, not after every parameter change.
Because FUNC stays on after one press, the save completes even if FUNC is
still on or you enter an extension page while it runs.

For example, give a kick step P.03, leave PrEd and play: that choice is already
part of the current pattern. Save the pattern with WRITE when you want to
recall that version from a memory.

Here, a **part** is one of the ten sound parts; a **step** is one of the sixteen
sequencer positions. The pages control different things:

| Setting | Applies to |
| --- | --- |
| Predictability, Time | Each step of each part |
| Bar filter, Echo, Ratchet, scale | The selected part |
| Intra-bar loop | The whole pattern |
| LIVE gestures | The current performance; not stored in the pattern |
| rb.ty program, delay/freeze duration and playback controls | The current effect; not stored in the pattern |
| Captured freeze audio | A temporary recording; not stored in the pattern |

The first three rows are included when you save a pattern with WRITE.
Sample audio and global settings are separate from pattern memories.

## Opening and leaving a page

FUNC stays on after one press. Press it again to turn it off.

1. Select the part you want to edit.
2. Press FUNC to turn it on.
3. Turn SAMPLE/SELECT to choose an extension page.
4. **Press FUNC again to enter that page.**

Inside a page, **PART <** and **PART >** still change the part, and the page
follows it: the display stays on the page and shows the new part's values (the
bar filter shows its number), and LIVE beat repeat uses it from the next pad
press.

While you choose a page, the FUNC light stays on. Inside a page it blinks;
in LIVE the MUTE light blinks too.

LIVE is the first page in the menu. The display shows its name as PErF.

If you start WRITE (FUNC + MEMORY), step jump (FUNC + STEP) or active step
(FUNC + PLAY) while choosing a page, entering the page cancels it, as pressing
FUNC does on the standard Volca Sample. Its lights stop blinking and nothing
is saved.

To leave a page, press FUNC. This returns to page selection with FUNC on.
Press FUNC once more to return to ordinary controls.

| Page | SAMPLE/SELECT | Pads |
| --- | --- | --- |
| LIVE | With STEP on: OFF or 1–16 loop passes | Hold a performance effect; hold MUTE to mute parts; hold MEMORY to choose a pattern; with STEP on, set the loop |
| PrEd | Change Predictability for the steps you hold | Hold one or more steps |
| Bar filter | — | Toggle bars 1–8; pads 9–16 repeat the same eight choices |
| rb.ty | Choose reverb 0–2, delay 3 or freeze 4 | Set duration and control freeze |
| tIME | Change microtiming for the steps you hold | Hold one or more steps |
| ECho | Choose 0–4 extra hits | Pads 1–8 choose their spacing |
| rAtC | Choose 1–4 hits within a step | Pads 1–4 choose the same hit count |
| LooP | Set OFF or 1–16 total passes | Hold the first and last steps of the loop |
| SCAL | Choose scale 0–15 | Pads 1–16 choose the same scales |

With STEP on, PrEd and Time show the selected part's programmed notes once
you have entered the page with the second FUNC press. The note map is hidden
while you are still choosing a page with FUNC on.

Inside PrEd and Time, pads select steps for that page's parameter. They do
not add or remove notes. The other parameter knobs are suspended until you
leave the page. A knob moved during this time can apply its current position
when ordinary control resumes. With STEP off, only the pads you hold are lit.

Outside extension pages, STEP editing keeps its ordinary role. With STEP and
FUNC both on, pads still edit notes while FUNC changes the knobs' functions.
This is where you arrive when you leave LIVE with STEP still on after setting
the loop there: turn STEP off before pressing FUNC if you only want to change
page.

## Predictability: choose which bars play a step

Predictability repeats over **eight bars**. Each step of each part has its
own choice: **ALL plus P.01–P.23**, making 24 choices in total.

For example, put a kick on step 1 and give it P.03. It plays on bars 1 and 5.
Give another kick step ALL and it plays on every bar, subject to the part's
bar filter.

1. Open PrEd for the part you want to edit.
2. Hold one or more step pads.
3. Turn SAMPLE/SELECT to change the choice for those steps.

The display shows the choice of the lowest-numbered pad you hold. Turning
without holding a pad changes nothing. Setting a choice on an empty step does
not create a note. Initializing a pattern sets every choice to ALL.

Read left to right: each symbol is one bar, from 1 to 8. `X` allows the step
to play; `0` skips it. All parts share the same bar count.

| Setting | Bars 1–8 |
| --- | --- |
| ALL | `XXXXXXXX` |
| P.01 | `X0000000` |
| P.02 | `0000000X` |
| P.03 | `X000X000` |
| P.04 | `000X000X` |
| P.05 | `X0X0X000` |
| P.06 | `000X0X0X` |
| P.07 | `X0X000X0` |
| P.08 | `X00X00X0` |
| P.09 | `X000X0X0` |
| P.10 | `X0X0X0X0` |
| P.11 | `0XXXXXXX` |
| P.12 | `XXXXXXX0` |
| P.13 | `0XXX0XXX` |
| P.14 | `XXX0XXX0` |
| P.15 | `0X0X0XXX` |
| P.16 | `XXX0X0X0` |
| P.17 | `0X0XXX0X` |
| P.18 | `0XX0XX0X` |
| P.19 | `0XXX0X0X` |
| P.20 | `0X0X0X0X` |
| P.21 | `XXXX0000` |
| P.22 | `0000XXXX` |
| P.23 | `00X00X00` |

## Bar filter: leave a whole part out of a bar

The bar filter has **eight independent choices for each part**. Open its page
and use pads 1–8 to allow or exclude the part in bars 1–8. Lit means allowed;
unlit means excluded. Pads 9–16 repeat the same eight choices.

For example, excluding bar 5 leaves that part silent on bar 5 without changing
bar 1. Predictability and the bar filter both have to allow the original note.
If that note is skipped, its echoes and ratchets are skipped too. An excluded
open hi-hat does not suppress a closed hi-hat that is allowed to play.

Stop/Start restarts the bar count at bar 1. An intra-bar loop completes its
repeats before the count advances; each internal return stays in the same bar.
Manual triggers and LIVE beat repeat are independent of these two filters.

## Time: move a step earlier or later

Open tIME, hold the step pads you want to edit and turn SAMPLE/SELECT.
Negative values move hits earlier; positive values move them later. Zero keeps
their ordinary timing. The display shows the value of the lowest-numbered pad
you hold, even if an earlier step is lit in the note map.

Each step of each part has its own value, from **−15 to +15**. One unit is
1/32 of that step's duration. For example, +4 delays a hit by one eighth of
its step. Swing is included in that duration.

## Echo: add quieter hits after each note

Echo is a **per-part setting**. On ECho, turn SAMPLE/SELECT to choose **0–4
extra hits**. Zero adds none. Each echo is quieter than the previous hit.
Use a pad to choose the time between hits:

| Pad | Spacing in steps | Note value without swing |
| --- | --- | --- |
| 1 | 1/2 | 1/32 |
| 2 | 1 | 1/16 |
| 3 | 2 | 1/8 |
| 4 | 3 | Dotted 1/8 |
| 5 | 4 | 1/4 |
| 6 | 6 | Dotted 1/4 |
| 7 | 8 | 1/2 |
| 8 | 16 | One bar |

For example, choose 2 and pad 3: each original note of this part is followed
by two quieter hits, spaced two steps apart. The spacing follows the original
note's step duration, including swing. Echoes use that note's sound settings.

## Ratchet: divide each note into repeated hits

Ratchet is a **per-part setting**. On rAtC, press pad 1, 2, 3 or 4, or turn
SAMPLE/SELECT, to choose **one, two, three or four hits within a step**.
The number includes the original hit: 1 is ordinary playback, with no repeats.

For example, choose 3 for the snare part. Each programmed snare note that is
allowed to play becomes three evenly spaced hits within its step. Other parts
keep their own ratchet settings. Holding a step does not give it a separate
ratchet value.

### Timing limits

Echoes and ratchets follow the original sequenced note: if that note is
filtered out, its repetitions do not play. A muted part stays muted.

A very short preceding step can limit how far a hit can be moved early.
Extreme swing, clock changes and dense combinations can affect timing.
The number of scheduled hits and sounding voices is finite: some echoes can
be dropped, and a new voice can replace an older one.

## Intra-bar loop: repeat part of the pattern

Open LooP, then hold the first and last steps you want to repeat. If you hold
more than two pads, the outermost ones set the interval; one pad selects a
single-step loop. Turn SAMPLE/SELECT for **1–16 total passes**, or below 1
for OFF. Inside LIVE, STEP on gives you the same controls without leaving the
page; see [setting the loop from LIVE](#setting-the-loop-from-live).

For example, steps 1–8 with three passes play:
`1…8, 1…8, 1…8, 9…16`. One pass adds no repeat. OFF keeps the interval visible
without repeating it. New patterns start with steps 1–8, a pass count of three
and the loop OFF. Interval, count and ON/OFF choice belong to the current pattern.

Loop edits take effect after the next boundary the sequencer has already
selected. Notes moved early can finish a return that was already prepared.
An interval with no enabled steps is bypassed. A native step jump or pending
pattern/song change takes priority. Stop/Start and pattern load rearm the loop
from the current pattern's settings.

Saving with WRITE and taking an audio backup briefly suspend the loop, then
rearm it, unless a step jump or explicit cancellation has disabled that return.
Saving does not cancel a LIVE effect you are holding. LIVE presses, replacements
and releases keep the loop interval and remaining passes. Enabling a loop or
changing an enabled loop cancels LIVE.

## Scales, pitch envelope and sample zones

SCAL chooses a scale **for the selected part**. Use SAMPLE/SELECT for 0–15
or pads 1–16 for the same choices: pad 1 selects scale 0, pad 16 selects
scale 15. The scale maps semitone-mode SPEED relative
to the sample's original pitch; it does not detect or tune its root note.
FUNC+SPEED remains continuous.

| Number | Scale |
| --- | --- |
| 0 | Chromatic |
| 1 | Major / Ionian |
| 2 | Natural minor / Aeolian |
| 3 | Dorian |
| 4 | Phrygian |
| 5 | Lydian |
| 6 | Mixolydian |
| 7 | Locrian |
| 8 | Harmonic minor |
| 9 | Melodic minor, ascending |
| 10 | Major pentatonic |
| 11 | Minor pentatonic |
| 12 | Minor blues |
| 13 | Whole tone |
| 14 | Diminished, whole–half |
| 15 | Diminished, half–whole |

PITCH EG INT sets an envelope depth of about **−24…+24 semitones**, with zero
at the centre. ATTACK and DECAY choose musical lengths in these knob regions:

| Display code | Duration |
| --- | --- |
| 0 | Instant |
| 1 | 1/16 |
| 2 | 1/8 |
| 3 | Dotted 1/8 |
| 4 | 1/4 |
| 5 | Dotted 1/4 |
| 6 | 1/2 |
| 7 | One bar |

These lengths follow the straight clock before swing. FUNC keeps free timing
available. Existing free envelope values stay free until you edit them; motion
and held-step editing keep the chosen musical/free mode. The pitch envelope
moves continuously between its endpoints, independently of the scale.

FUNC+START and FUNC+LENGTH choose the start and end from sixteen equal zones
of the sample. The end cannot come before the start. The ordinary knobs keep
their continuous sample controls. Zone choices also work with motion.

## LIVE: temporary performance effects

Select a part, open LIVE and hold a pad. Pads 4–7 affect only the selected
part. The others affect all parts or the stereo master, as listed.
LIVE gestures are not stored in the pattern.

| Pad | Effect |
| --- | --- |
| 1 | All sounding voices one octave down, at half playback speed |
| 2 | All sounding voices one octave up, at double playback speed |
| 3 | Master gate: silence the stereo output in the second half of each swung step |
| 4–7 | Selected-part beat repeat at 1/8, 1/16, 1/32 or 1/64 |
| 8 | Vinyl stop, 1/2 note; return at the next qualifying sequenced note |
| 9 | Vinyl stop, 1/4 note; return at the next qualifying sequenced note |
| 10 | Vinyl stop, 1/8 note; return at the next qualifying sequenced note |
| 11 | Vinyl stop, 1/16 note; return at the next qualifying sequenced note |
| 12 | Backcue, 1/2 note; return at the next qualifying sequenced note |
| 13 | Backcue, 1/4 note; return at the next qualifying sequenced note |
| 14 | Backcue, 1/8 note; return at the next qualifying sequenced note |
| 15 | Backcue, 1/16 note; return at the next qualifying sequenced note |
| 16 | Scratch: repeated 1/16 braking with decreasing volume |

Pressing a new LIVE pad replaces the current effect. Releasing that pad does
not bring back an older one you are still holding. If several new pads are
pressed together, the lowest-numbered one wins.

### Muting parts without leaving LIVE

Hold **MUTE** to use the ordinary part-mute screen. While MUTE is held,
pads control mutes instead of starting LIVE effects. Release MUTE to return
to LIVE; the part mutes you chose stay in effect.

An effect already held when you press MUTE keeps running under its usual
rules. Release its pad to release the effect, even while MUTE is held.
The usual braking and return rules still apply.
That already-held pad does not also toggle a part mute. A pad used for mute
that is still down when you release MUTE does not start an effect: release
and press it again for a new LIVE gesture. MUTE works as usual outside LIVE.

### Choosing a pattern without leaving LIVE

Hold **MEMORY** and press a pad to choose a pattern, as outside LIVE. LIVE
stays open. When stopped, the pattern loads at once. While playing, it takes
over at the next step. Pads 11–16 choose song 1–6 as outside LIVE; a song
starts when the current pattern ends.

Loading the pattern ends the running effect, and its pad light goes out.
A pad that is still down when you release MEMORY does not start an effect:
release and press it again for a new LIVE gesture.

While MEMORY is held, every pad you hold counts, including the pad of a
running effect. The highest pad 1–10 chooses the pattern. If you hold only
pads 11–16, the highest chooses the song. Each press or release while
MEMORY is down chooses again. Releasing MEMORY confirms the choice. Release
the effect's pad first when you want a lower pattern.

### Setting the loop from LIVE

Press **STEP** inside LIVE to use the pads and SAMPLE/SELECT as on the LooP
page: hold the first and last steps of the interval, and turn SAMPLE/SELECT
for 1–16 passes, or below 1 for OFF. The display and pad lights are LooP's,
and the STEP light stays on. Turning STEP on ends the effect you are holding,
or one still waiting to return, as leaving LIVE does.

Press STEP again to return to the effects. The loop keeps running with its
interval and remaining passes, and the effects play over it. A pad still down
when you turn STEP off does not start an effect: release it and press it
again.

This is the pattern's own loop setting, the one LooP edits: WRITE saves it,
and it stays when you leave LIVE. Edits that LooP would refuse, for example
while WRITE is saving, are ignored here too.

MUTE and MEMORY work as described above while STEP is on; release them to
return to the loop controls. A pattern you load keeps STEP on and shows its
own loop. Choosing a song with pads 11–16 turns STEP off, as it does outside
LIVE, and brings the effects back. While a song is active, STEP cannot be
turned on.

As in ordinary STEP editing, turning a knob while you hold pads stores its
value in those steps of the selected part as step motion. Set the interval
first and release the pads before you use the knobs. With no pad held, a knob
changes the part as usual.

If you leave LIVE with STEP on, PrEd and Time show the notes as usual, and
LIVE opens again with the loop controls.

### Octaves and beat repeat

Pads 1–2 change sounding voices immediately, including fading tails. They
keep each note's pitch envelope and SPEED settings. Release to restore ordinary
speed; samples continue from their current positions rather than restarting.
Reverb, delay and freeze audio already captured keeps its own rate.
Samples still stop at their endpoints.

Beat repeat starts at the next step boundary and follows swing. While held,
it replaces the selected part's sequenced hits, echoes and ratchets, using
that part's current sound settings. Other parts keep playing. Mute, voice
limits and hi-hat exclusion still apply. Missed subdivisions are skipped.

### Vinyl stop and backcue

**Vinyl stop, pads 8–11**, slows each voice to zero in its current direction.
A forward-playing sample keeps moving forward; a sample already in reverse
keeps moving backward. **Backcue, pads 12–15**, reverses each voice's direction
while slowing it to zero. Both use the same four braking lengths:

| Note length | At 120 BPM |
| --- | --- |
| 1/2 | 1000 ms |
| 1/4 | 500 ms |
| 1/8 | 250 ms |
| 1/16 | 125 ms |

The length uses the clock at the moment you press the pad, before swing.
The sequencer must be running and a usable clock must be available.

Release before braking finishes to restore ordinary playback immediately.
After a complete brake, the output waits for the **next qualifying original
sequenced note**. That note must:

- pass Predictability and the part's bar filter;
- belong to an enabled, unmuted part;
- have an available sample and nonzero volume;
- survive the exclusive hi-hat rule.

The return happens at that note's scheduled time, including microtiming.
Echoes, ratchets, manual triggers and beat repeat do not trigger this return.
The automatic return can happen while you still hold the pad. Release it and
press again to start another brake.

### Scratch

Pad 16 restarts a braking ramp every straight 1/16 while you hold it. The
master volume falls through 100%, 87.5%, 75%, 62.5%, 50%, 37.5%, 25% and 12.5%
over the first eight cycles, then reaches zero. The effect stays active and
silent while held.

Release to wait for the next qualifying original sequenced note, using the
same conditions above. Even a short scratch press waits for that note after
release. It then restores ordinary direction, speed and volume. Scratch acts
on the voices currently playing: it does not record a loop, reset sample
positions or restart voices that have ended.

### Endpoints, loops and leaving LIVE

A voice that reaches its sample endpoint ends normally; returning from a
LIVE effect does not restart it. Backcue can move a non-looped slice before
its selected start, within the original sample. Looped slices keep their bounds.
Scratch's volume change affects the stereo master, including effect tails.

Leaving LIVE, turning STEP on, pressing Stop, loading a pattern, initializing
or starting an audio backup cancels LIVE and restores ordinary playback
without waiting for a musical boundary. LIVE effects do not change the saved
notes or motion. They keep the intra-bar loop and its remaining passes as
described in the loop section.

## rb.ty: reverb, delay and freeze

Open rb.ty and turn SAMPLE/SELECT:

| Program | Effect |
| --- | --- |
| 0–2 | Native reverbs |
| 3 | Mono lo-fi delay |
| 4 | Freeze |

Only one of these programs runs at a time. LIVE can run alongside it.
Delay and freeze receive the **mono effect send**, not the whole stereo mix.
A part whose send is off remains audible directly but does not feed them.

The program, delay/freeze duration, speed, direction and stop state are live
effect controls, separate from pattern storage. WRITE does not store them or
the captured audio. Opening rb.ty again keeps the current effect; changing
to another program clears its audio history. Changing to delay starts with
two steps; changing to freeze starts with one step, normal speed and no reverse.

### Try delay, then capture a loop

1. Choose a part with a sustained sound or a busy rhythm. Outside extension
   pages, turn STEP off. If its effect send is off, press FUNC, hold **PART >**,
   press that part's pad (1–10), release PART > and turn FUNC off. This toggles
   the send: do it only if you need to turn the send on.
2. Set REVERB MIX near the middle. Open rb.ty, choose **3**, start the sequencer
   and press **pad 2** for a two-step delay.
3. Choose **4** and press **pad 4**. Freeze records four steps starting at the
   next step boundary, then repeats them. Use a sound that continues through
   that window: a short capture between sparse notes can record silence.
4. Try pads **9–12** to change that same fragment. Press transport Stop to
   hear it without the sequencer. Lower MIX to zero and raise it again: the
   fragment is still there.
5. Press **pad 5** to stop the frozen loop.
6. To record another fragment and resume, start the sequencer and press one
   of **pads 1–4**. Speed, reverse and MIX do not restart a pad-5 stop.

### Duration and freeze controls

Pads 1–4 select one, two, three or four straight steps: a sixteenth, eighth,
dotted eighth or quarter note. At 120 BPM these last 125, 250, 375 and 500 ms.
Longer windows reduce the storage sample rate; tempo-change artifacts are part
of the lo-fi effect.

In freeze, pressing any of pads 1–4 requests a new recording at the next
step boundary, even if that duration is already selected. The sequencer needs
to be running for a new capture.

| Freeze pad | Action |
| --- | --- |
| 1–4 | Choose a duration, record a new fragment and resume after a pad-5 stop |
| 5 | Stop the loop and cancel a pending recording; keep program 4 selected |
| 9 | Play the existing fragment at half speed |
| 10 | Play it at normal speed |
| 11 | Play it at double speed |
| 12 | Toggle its playback direction |

Pads 9–12 change the existing fragment, including while the sequencer is
stopped. They do not record another one. Pad 15 lights while a recording is
pending; pad 16 indicates an unavailable clock or capture window. A request
that cannot be carried out leaves the last valid audio state in place.

With freeze, REVERB MIX adds the frozen loop to the direct sound. At zero,
only the direct sound is heard. Turning MIX down does not stop or erase the
recording; raising it brings that same loop back. You can capture at MIX zero.
Programs 0–3 keep their native MIX/send behaviour.

Transport Stop keeps an active frozen loop playing. Start requests another
capture with the selected controls. A **pad-5 stop stays stopped** through
Stop/Start, page exit and speed/reverse changes. Resume with a new recording
from pads 1–4. Switching to another program and back to 4 also starts a new
capture; simply reopening rb.ty does not.

Audio backup clears effect history. Delay resumes empty. An active freeze
needs a new capture with the selected controls; a pad-5 stop remains stopped.

## Patterns and Studio

DataBeat OS uses **the DataBeat OS 1.0 pattern format**. The firmware does not
convert patterns from other formats.

Studio identifies and archives backups in this format. A complete audio backup
contains the ten stored pattern memories **and a separate snapshot of the
pattern currently in use**, including edits you have not saved with WRITE.

VolcaStudio XL restores these memories in the **DataBeat OS 1.0 pattern
format**. A backup can contain memories in other formats; only the compatible
ones are restored. Restoring the current snapshot to a memory requires an
explicit destination. VolcaStudio XL's groove templates change only the
microtiming of these patterns.

Pattern backups do not contain sample audio, global settings, LIVE gestures
or captured effect audio. Keep your sample library and original backups.
For the app's procedure, see [VolcaStudio XL pattern banks](patterns.md).

## MIDI

Standard Korg MIDI control and synchronization remain available. Pajen's Omni,
polyphonic and channel-11 modes, chromatic MIDI-note response and additional
MIDI controls are not included. Studio uses MIDI to request an audio pattern
backup and, optionally, reset the current edit buffer.

Do not send a pattern over MIDI while WRITE is still saving. The memory being
saved can receive the incoming pattern, or part of it, instead of the one you
wrote, as on the standard Volca Sample.

**MIDI control change 49 sets a part's volume, and WRITE saves it.** Each
pattern stores a volume for every part, separate from LEVEL. No panel control
changes it. LEVEL multiplies it, so turning LEVEL up cannot make up for a lower
volume. A control change 49 received on the part's channel (channels 1–10 for
parts 1–10) sets the volume to the value received; control change 7 sets LEVEL
instead. Note velocity does not change the volume: every note received plays
the part at its stored volume. The new volume applies at once and WRITE saves
it with the pattern, so a low value can lower the part persistently, with
nothing on the panel to show it: at 64 a part plays about 12 dB below its
level at 127, and at 0 it is silent. To restore full volume, send control
change 49 with value 127 on that channel and save with WRITE, select a memory
whose parts are at 127, or restore the pattern from Studio (SYRO) with its
parts at 127. This is the behaviour of the original Volca Sample firmware, kept
on purpose. The firmware initializes the volume to 127, and Studio's neutral
patterns use 127.
