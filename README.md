# vlog

CLI for recording Linux desktop videos with webcam picture-in-picture, synced audio, playback, and recording management.

## Requirements

- Linux
- `ffmpeg`
- `ffplay` (for `vlog p -l` and `vlog a`)
- Webcam device (`/dev/video*`)
- Wayland sessions: `wf-recorder`
- X11 sessions: `ffmpeg` with `x11grab` and PulseAudio/PipeWire `pulse` input

## Commands

Start recording:

```bash
vlog r
```

Stop recording and finalize output:

```bash
vlog s
```

Webcam align preview (live):

```bash
vlog a
```

Play most recent recording (detached/background):

```bash
vlog p -l
```

Clear all saved recordings:

```bash
vlog c
```

Version / upgrade / help:

```bash
vlog -v
vlog -u
vlog -h
```

## Output and behavior

- Default output directory: `~/Vlogs`
- Output filename format: `vlog_YYYYMMDD_HHMMSS.mp4`
- Single active recording enforced
- Single CLI instance lock enforced
- Progress messages shown during start/stop/finalization

## Recording pipeline

`vlog r` starts two captures:

1. Screen-only capture
  - Wayland: `wf-recorder`
  - X11: `ffmpeg x11grab`
2. Webcam + default audio capture (single process for A/V sync)

`vlog s` stops both captures, then finalizes into one MP4 by:

- Converting screen to grayscale
- Overlaying webcam at bottom-right edge (no padding)
- Using webcam-capture audio track (keeps webcam/audio sync)
- Web-optimized H.264/AAC output settings

## Video style

- Main screen: grayscale
- Webcam overlay: grayscale + boosted contrast/deeper blacks
- Webcam overlay width: 360px (scaled with aspect ratio preserved)
- Overlay position: bottom-right edge

## Auto trim (audio-bump based)

After finalization, output is auto-trimmed using audio activity detection:

- Start trim: `0.8s` before first detected audio bump
- End trim: `0.5s` after last detected audio bump
- Noise-aware thresholding is used to handle background noise
- If no reliable bump window is found, full video is kept

## Install from releases

Installer script (repo `ryangerardwilson/vlog`):

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/vlog/main/install.sh | bash
```

Install a specific release:

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/vlog/main/install.sh | bash -s -- --version 0.1.0
```

After install:

```bash
vlog -h
```

## Release automation

GitHub Actions builds Linux x86_64 release artifacts on tags matching `v*`:

- `.github/workflows/release.yml`

## Files

- `main.py`: CLI entrypoint
- `install.sh`: installer/updater
- `.github/workflows/release.yml`: release build and publish workflow
- `.github/scripts/find-python-url.py`: helper for standalone Python URL resolution
