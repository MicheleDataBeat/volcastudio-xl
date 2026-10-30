# VolcaStudio XL Browser App quick start

Prepare and send a sample kit with VolcaStudio XL Browser App 1.1.0, a locally
installed application that opens in Google Chrome. No terminal is needed.

## 1. What you need

- A computer with Windows 10/11 x64, macOS on Apple silicon or Linux x86-64
  (glibc 2.35 or later).
- **Google Chrome** — free from google.com/chrome.
- An original **Korg Volca Sample** (first generation) running DataBeat OS 1.0 for
  patterns and grooves. To install DataBeat OS 1.0, download Korg's official
  `volcasample_updater_1_42.zip` from korg.com and add it in **Firmware** with
  **Choose the Korg 1.42 updater…**: the Browser App builds DataBeat OS 1.0 from it
  and checks the result. Studio contains no firmware.
- A **3.5 mm audio cable** from the computer's headphone/line output to the
  Volca's **SYNC IN** socket.

## 2. Download and open

1. On the [download page](https://micheledatabeat.github.io/volcastudio-xl-releases/) press **Download Browser App**. Check that the suggested package matches your system and CPU architecture; **All downloads** lists the alternatives.
2. Extract the download and open **VolcaStudio XL Browser App**, following the steps for your system below.
3. The local helper opens the Browser App in Chrome. You do not need to type an address.

Packages are unsigned. Verify the download against `SHA256SUMS` on the
[VolcaStudio XL release page](https://github.com/MicheleDataBeat/volcastudio-xl-releases/releases).
Use the following opening exception only for that verified copy, if you trust it.

- **Windows:** right-click the ZIP → **Extract All** → open the folder →
     double-click **VolcaStudio XL Browser App**. If *Windows protected your PC* appears,
     click **More info → Run anyway** (first time only).
- **macOS:** open the ZIP and drag **VolcaStudio XL Browser App** into **Applications**,
     then open it. If macOS says it cannot verify the developer, open
     **System Settings → Privacy & Security** and click **Open Anyway** (first time only).
- **Linux:** extract the archive, open the folder, double-click
     **VolcaStudio XL Browser App** (or right-click → **Run as a program**).

Opening the Browser App again opens another window of the running session.

## 3. Choose your samples

1. In **01 Gathering** click **Add samples…** (or **Add a folder…**) and pick
   your WAV files. The Browser App stores imported copies in its library folder.
   To use an existing folder in place, choose **Manage libraries…**, enter its full
   path and choose **Register folder**. It also becomes available in the Desktop App.
2. Click a sample to select it. Hold **Shift** to select a range, **Ctrl**
   (Windows/Linux) or **⌘** (Mac) to pick several.
3. Route **Chrome's sound output** to speakers or headphones, away from **SYNC IN**.
   **Listening source** offers **Source audio** or **Volca preview (mono, 31.25 kHz)**.
   Press **Space** to listen; **Stop** ends playback. **Autoplay selection** listens
   as you select individual samples. The output chosen in Connections is for
   transfers; it does not change Chrome's listening output.
4. Press **Enter** to put the selection on the **workbench**.

Choose **All samples** to search all available libraries, saved kits and variants.
Use **Previous page / Next page** for more results, and **Refresh** after files
change outside the Browser App. **Manage libraries… → Unregister** removes a folder
reference, including one on a disconnected drive; it leaves the files in place.

## 4. Prepare the kit

- Put samples in the order you want with **↑ ↓**, **Alt+↑/↓** or by dragging.
- Keep an eye on the meter: up to **100 samples** and **65 seconds**.
- Optional: select workbench rows and press **J** (lower) or **K** (raise), type a
  number of semitones (0–99) and press Enter. Optional: **Align keys…** proposes
  transpositions to match a reference sample’s pitch class. Review uncertain
  samples; they stay unchanged unless you adjust them. Nothing changes until
  you press **Accept proposal**. Varispeed changes both pitch and duration.
- **Make ×2 variant** (**Ctrl/⌘+D** in either sample list) adds a version one octave
  higher and half as long, keeping existing workbench entries. J/K replaces the
  selected workbench entries. From the library it replaces matching entries
  already in the workbench, or adds the variant if its source is not included.
- Type a **kit name** (lowercase, e.g. `dusty-breaks`) and click **Save as new kit**.

## 5. Transfer

**Sending a kit clears all 100 sample slots on the Volca first.** Keep copies
of any sample audio you want to reload.
A pattern backup does not contain sample audio and cannot recover samples
cleared from the instrument.

1. Connect the cable: computer audio output → Volca **SYNC IN**. Disconnect speakers
   and headphones from that output: the computer will play data signals. Pause
   music, videos and notifications; disable EQ and other audio processing.
2. Open **06 Connections** and choose that output under **Transfer output → SYNC IN**.
3. Back in **Gathering**, click **Send saved kit to Volca…**. The Browser App prepares
   the signals and shows a summary. Read it, then click **Clear & send**
   (or **Cancel — keep the Volca as it is**).
4. Wait until **Signals sent** appears, then check the samples on the Volca.

**Signals sent** means the computer finished playing the transfer signals.
The SYNC IN connection sends no acknowledgement back to the Browser App. Confirm
the samples and their order on the Volca before relying on the transfer.

To keep prepared signals for later, save the kit first. **The clear/upload WAVs
are data signals: do not audition them through speakers or headphones. Playing
the clear signals to SYNC IN erases all 100 slots.** Choose **Download SYRO files…**,
then **Prepare download**. The Browser App downloads a ZIP and sends nothing to the Volca.

## Optional: back up and restore patterns

A pattern backup saves the ten pattern memories and a current-edit snapshot.
It does not save sample audio or all GLOBAL settings.

You need a USB-MIDI interface (computer → Volca **MIDI IN**) and a cable from the
Volca **headphone** output to your computer's audio input. In **Connections**
choose the **Backup input** and the **MIDI output**, then in **03 Memory** type a
name, click **Capture backup** and confirm with **Start capture**. Don't touch
the Volca for about two minutes.
macOS asks for **microphone** permission the first time: click **Allow**.
The Browser App saves a bank only after it receives all eleven complete frames.

Restoring replaces the pattern memories you select. In **Memory**, open the
saved bank, tick the memories to replace and choose **Restore selected memories…**.
Review the destinations before confirming. The extra current snapshot needs
**Restore snapshot…** and an explicit destination. Check a restored memory
on the Volca after **Signals sent**.

**Do not audition pattern SYRO WAVs through speakers or headphones.** To prepare
files without sending, choose **Download selected SYRO files…**. For the current
snapshot, first choose its destination memory (1–10), then **Download snapshot SYRO…**.
Playing those files to SYNC IN replaces the specified stored memories.

For grooves, open **04 Movement**. Choose stored memories or the bank's current
snapshot with an explicit destination, assign templates per part, then choose
**Review change plan** before saving. The catalogue lists all sixteen offsets
and identifies measured, reconstructed and analytic steps. The
[Browser App guide](https://micheledatabeat.github.io/volcastudio-xl-releases/docs/browser.html)
explains source copies and rollback files.

## If something goes wrong

| Message | What to do |
| --- | --- |
| *Choose the audio output…* | Go to **Connections** and choose the output wired to SYNC IN. |
| *… is not connected* | Plug the interface back in, click **Refresh devices**, choose it again. |
| *The audio input could not be opened* | Allow microphone access: macOS **System Settings → Privacy & Security → Microphone**; Windows **Settings → Privacy & security → Microphone** (“Let desktop apps access your microphone”). |
| *Google Chrome was not found* | Install Chrome from google.com/chrome and open VolcaStudio XL Browser App again. |
| *This window belongs to a closed Browser App session* | Open VolcaStudio XL Browser App again. |
| The meter is red | Remove samples or shorten some with **K** (higher = shorter). |
| *Stopped while sending* during a kit transfer | Some slots may be cleared or loaded. Check the connection, then resend the complete kit when ready. For an interrupted firmware update, stop and consult the firmware guide. |
| Samples on the Volca sound wrong or are missing | Check the cable goes to SYNC IN, turn the output volume up (no distortion), disable sound effects/EQ, and send again. |

**Connections → Check installation** shows installed tools and Studio's folders
without opening audio or MIDI devices. It does not check the instrument or cables.

To finish, click **Close Browser App** (top right). Your kits and workbench are kept.
More details: [Browser App guide](https://micheledatabeat.github.io/volcastudio-xl-releases/docs/browser.html).
