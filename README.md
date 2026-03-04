# vlog

CLI for recording your Linux desktop and managing recordings.

## Requirements

- Linux
- Wayland: `wf-recorder` (recommended)
- X11: `ffmpeg` with `x11grab`
- `ffplay` (optional, for playback command)

## Usage

Start recording:

```bash
vlog r
```

Stop recording:

```bash
vlog s
```

Play latest recording (detached/background):

```bash
vlog p -l
```

Clear all recordings:

```bash
vlog c
```

Show version / upgrade / help:

```bash
vlog -v
vlog -u
vlog -h
```

Notes:

- Default output directory is `~/Vlogs`
- Recordings are grayscale, web-optimized (HD-light settings), and include default-device audio
- Webcam video is composited live in the bottom-right corner
- Capture is done as a single live pipeline to keep audio/video/webcam aligned
- Only one active recording is allowed at a time

## Install from releases

Installer script (repo `ryangerardwilson/vlog`):

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/vlog/main/install.sh | bash
```

Install a specific release:

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/vlog/main/install.sh | bash -s -- --version 0.1.0
```

After install, run:

```bash
vlog -h
```

## Release automation

GitHub Actions workflow builds a Linux x86_64 binary tarball on tags matching `v*` and uploads it as a release asset:

- `.github/workflows/release.yml`

## Files

- `main.py`: CLI entrypoint
- `install.sh`: release installer
- `.github/workflows/release.yml`: release build and publish workflow
- `.github/scripts/find-python-url.py`: helper for standalone Python URL resolution
