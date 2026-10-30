# Firmware: DataBeat OS and the Korg updater

**Returning to Korg?** Power on with **MEMORY + PLAY** to enter forced
update mode. Select the original Korg updater in Studio and wait for
**End on the Volca**. See [Return to Korg firmware](return-to-korg.md).

VolcaStudio XL installs **DataBeat OS 1.0** on the **first-generation Korg
Volca Sample** (Volca Sample 2 is not supported). Studio contains no firmware.
You download the official Korg updater yourself; Studio builds DataBeat OS 1.0
from it on your computer, checks the result and keeps both in its firmware
library:

- **DataBeat OS 1.0**: to install DataBeat OS (production, hardware tested);
- **Korg volca sample 1.42**: to return the instrument to Korg's own firmware.

The firmware list shows exactly these two entries, in the Desktop App and in
the Browser App. Studio contains the pinned DataBeat OS patch, not complete
firmware. DataBeat OS offers Predictability with 24 choices, eight independent
bar choices per part, vinyl stop on LIVE pads 8–11 and visible notes in PrEd
and Time. At startup the display scrolls **dAtAbEAt OS**. See the
[DataBeat OS manual](databeat-os-manual.md).

## 1 · Download the official Korg updater

1. Open Korg's
   [volca sample download page](https://www.korg.com/us/support/download/software/0/370/1475/).
2. Read Korg's software licence agreement shown on that page. Downloading means
   you accept it.
3. Under **System Updater**, download version **1.42**:
   `volcasample_updater_1_42.zip` (about 3.1 MB). Version 1.3.0 cannot be used.
4. Keep the zip as it is. Studio accepts the zip itself or the
   `volcasample_sys_0142.wav` inside it. Do not convert, trim or re-save the WAV.

If the download page moves, search Korg's support site for *volca sample
System Updater 1.42*. Expected SHA-256 values, if you want to check:

| File | SHA-256 |
| --- | --- |
| `volcasample_updater_1_42.zip` | `f0df310b8bd43b6367dbd0c54ba75e3db53942087e1a4b1ae049f8f08e1731f3` |
| `volcasample_sys_0142.wav` (inside the zip) | `8fe4f43c333a753d589a4d7eff7859e8fce7155cf54b889f4848d595721a55a9` |

On Linux use `sha256sum FILE`, on macOS `shasum -a 256 FILE`, on Windows
`Get-FileHash FILE -Algorithm SHA256`. Studio checks the WAV for you anyway.

## 2 · Add it to Studio

| App | Where | Action |
| --- | --- | --- |
| Browser App | **Firmware** | **Choose the Korg 1.42 updater…** |
| Desktop App | **04 / Firmware** | **Add Korg 1.42 updater…** |

Studio reads the updater, builds DataBeat OS 1.0 and checks the result: the
updater and the built image must match their pinned SHA-256 values, or nothing
is saved. Any other file is refused. Building takes a few seconds, needs no
internet connection and plays no audio. Adding the same file again changes
nothing.

## 3 · Install DataBeat OS (or restore Korg 1.42)

Use reliable power. Stop other computer audio, including notifications.

1. Select **DataBeat OS 1.0**, or **Korg volca sample 1.42** to return to
   Korg's firmware.
2. Choose the audio output connected directly to the Volca's **SYNC IN**.
   Disconnect speakers and headphones from that output. Disable EQ,
   normalization, crossfade and other audio processing.
3. To install DataBeat OS, power on with **FUNC + PLAY**; the display reads
   **UPdt**. To return to Korg, power on with **MEMORY + PLAY** instead; the
   display reads **UPdt with the final dot lit**. Release the buttons before
   sending. Normal update mode can reject the older Korg updater with a version
   error.
4. Start the guided update in Studio with **Begin update…** and confirm. Do
   not interrupt playback or switch off the Volca. The transfer lasts about 40 seconds.
5. Wait for **End** on the Volca, then power off and on again. At startup the
   display scrolls **dAtAbEAt OS**.

Studio asks for confirmation before sending. Firmware audio is a data signal:
never listen to it through speakers or headphones. **Signals sent** means the
computer finished playing; it is not installation confirmation. Check **End**
on the instrument. There is no automatic retry, and cancelling cannot undo a
partially received update.

## Returning to Korg

Keep a backup of your DataBeat OS patterns, select **Korg volca sample 1.42** in
Studio and power on the Volca with **MEMORY + PLAY**. Wait for **UPdt with
the final dot lit**, then release the buttons and confirm the transfer.
Use the original Korg updater; no intermediate firmware or factory reset is
needed. Follow the [full return procedure](return-to-korg.md).

If Studio shows **FUNC + PLAY**, use **MEMORY + PLAY** for this return.
Changing firmware does not convert pattern memories or make DataBeat OS's extra
settings available in Korg.

## After restarting

- The version check (power on while holding REC) can show **1.60**: this is the
  updater header version used by DataBeat OS, not the pattern format.
- You do not need to install Korg 1.42 before DataBeat OS. Studio only uses
  Korg's updater file to build DataBeat OS.
- Saved samples remain. DataBeat OS uses the **DataBeat OS 1.0 pattern format**;
  see the [DataBeat OS manual](databeat-os-manual.md) and
  [pattern banks](patterns.md). Installing firmware does not convert the stored
  memories, and Studio does not convert banks: memories in another format stay
  in your backups and are not restored.

## Rights

The Korg updater remains Korg's and is used under Korg's licence agreement on
your own computer. Studio contains only DataBeat OS's own changes and
instructions for applying them to your copy; it distributes no Korg firmware.
DataBeat OS is unofficial and not affiliated with or endorsed by Korg. See the
third-party notices included with Studio.
