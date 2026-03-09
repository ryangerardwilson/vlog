# blog

Terminal-native publisher and recorder that shells out to `x` and `linkedin`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/blog/main/install.sh | bash
```

## Usage

```text
blog CLI

flags:
  blog -h
  blog -v
  blog -u

features:
  publish text or media to the configured downstream CLIs
  # blog <text> | blog -m <path> [<text>] | blog -e
  blog "ship the patch"
  blog -m ~/media/demo.mp4 "ship the patch"
  blog -e

  start recording, optionally with sync diagnostics
  # blog -rec [-ds] [-o <path>]
  blog -rec
  blog -rec -ds

  stop recording, trim, and publish
  # blog -stp
  blog -stp

  stop recording, trim, and save ./output.mp4 without publishing
  # blog -rectest
  blog -rectest

  inspect or clean the recording workspace
  # blog -a | blog -pl [-o <path>] | blog -c [-o <path>]
  blog -a
  blog -pl
  blog -c
```

After `-stp`, recorder cache files in the output directory are auto-cleared.

## Config

Config path:

```text
~/.config/blog/config.json
```

Auto-created on first publish if missing. Template in repo: `template_config.json`

Default:

```json
{
  "publish": {
    "x": {
      "command": ["x", "p"],
      "text_args": ["{text}"],
      "media_args": ["-m", "{media}"]
    },
    "linkedin": {
      "command": ["linkedin", "p"],
      "text_args": ["{text}"],
      "media_args": ["-m", "{media}"]
    }
  }
}
```

Config forms:
- Simple: `"x": "x"` or `["x"]`, which appends text and media positionally.
- Structured: `command` + `text_args` + `media_args`, recommended when the downstream CLI uses a verb such as `p` and expects an explicit media flag.

Placeholder tokens:
- `{text}` becomes the post text.
- `{media}` becomes the media path.

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

## Source Run

```bash
python -m venv .venv
source .venv/bin/activate
python main.py -h
```
