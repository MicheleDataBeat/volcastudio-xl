# Changelog

## 1.1.0 — 30 October 2026

- Two editions: the VolcaStudio XL Desktop App and the VolcaStudio XL Browser
  App. Packages are named `VolcaStudio-XL-Desktop-<version>-<platform>` and
  `VolcaStudio-XL-Browser-<version>-<platform>`. The firmware section of both
  editions is called **Firmware**; the Desktop App's pages are **Sections**.
- One firmware entry: **DataBeat OS 1.0**, built on the computer from the user's
  own Korg volca sample System Updater 1.42 and checked against its pinned
  SHA-256 (image `13c0652b…a918`, updater WAV `d5d51b35…ba52`). It is a
  production release, accepted on the instrument. **Korg volca sample 1.42**
  remains available to return to Korg's firmware. DataBeat OS 1.0 is the
  internal build 1.1.0-experimental.4; the map between the two numbers is kept
  in `tools/make_lumon_patch.py` (`PUBLIC_RELEASES`).
- One pattern format: the **DataBeat OS 1.0 pattern format**. Backups, restores,
  neutral patterns and grooves use it. Banks in another format stay archived
  byte for byte and are not restored; Studio does not convert banks.
- The groove editor works on DataBeat OS 1.0 patterns and changes only the
  microtiming bytes. A stock pattern takes the DataBeat OS 1.0 format exactly
  when a groove is applied.
- Keep newly opened banks and newly built firmware visible when an older
  background refresh finishes later.
- Guides: Desktop App, Browser App, firmware, patterns and grooves describe the
  current workflow; the DataBeat OS 1.0 manual is included in every package and
  on the download page.
