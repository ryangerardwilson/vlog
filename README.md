# blog

CLI to publish to X + LinkedIn, with optional media, and optional built-in screen recording.

## Core flow

Publish text to all configured platforms:

```bash
python main.py "hello, world"
```

Compose in `$EDITOR` and publish:

```bash
python main.py -e
```

Publish with media:

```bash
python main.py "hello, world" -m /path/to/media.mp4
```

Media-only publish (no post text):

```bash
python main.py -m /path/to/media.mp4
```

## Recording flow

Start recording:

```bash
python main.py -rec
```

Stop recording, open trim UI, prompt for publish text, then publish:

```bash
python main.py -stp
```

Stop recording, open trim UI, and save local test output to `./output.mp4` (no social publish):

```bash
python main.py -rectest
```

After `-stp`, recorder cache files in the output directory are auto-cleared, so they do not accumulate.

## Other flags

- `-u`, `--upgrade`: upgrade to latest release
- `-v`, `--version`: print version
- `-h`, `--help`: show help
- `-o`, `--output-dir`: recording directory (default: `~/.cache/blog/recordings`)
- `--align`: webcam preview helper
- `--play-latest`: detached playback of latest recording
- `--clear`: clear saved recordings

## XDG config

Config file:

```text
~/.config/blog/config.json
```

Auto-created on first publish if missing.
Template in repo: `template_config.json`

Default:

```json
{
  "publish": {
    "x": {
      "command": ["x"],
      "text_args": ["{text}"],
      "media_args": ["{media}"]
    },
    "linkedin": {
      "command": ["linkedin"],
      "text_args": ["{text}"],
      "media_args": ["{media}"]
    }
  }
}
```

Config supports two forms:
- Simple: `"x": "x"` (blog app appends text/media positional args)
- Structured: `command` + `text_args` + `media_args` (recommended for custom CLIs)

Placeholder tokens:
- `{text}` -> post text
- `{media}` -> media path

Example custom integration:

```json
{
  "publish": {
    "x": {
      "command": ["myx", "publish"],
      "text_args": ["--caption", "{text}"],
      "media_args": ["--file", "{media}"]
    }
  }
}
```

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/blog/main/install.sh | bash
```
