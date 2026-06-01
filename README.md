# blog

Terminal-native publisher and recorder that shells out to `x` and `linkedin`.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ryangerardwilson/blog/main/install.sh | bash
```

If `~/.local/bin` is not already on your `PATH`, add it once to `~/.bashrc`
and reload your shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
source ~/.bashrc
```

`blog version` prints the installed app version from `_version.py`. Source checkouts
keep the checked-in placeholder at `0.0.0`; tagged release builds stamp the
shipped artifact with the real version.

## Usage

```text
blog CLI

global actions:
  blog help
  blog version
  blog upgrade

features:
  open the publish config in the editor
  # blog config
  blog config

  publish text or media to the configured downstream CLIs
  # blog publish <text> | blog publish media <path> body <text> | blog publish in editor
  blog publish "ship the patch"
  blog publish media ~/media/demo.mp4 body "ship the patch"
  blog publish in editor

  start or stop the local recording flow
  # blog record start | blog record stop and publish | blog record stop and save
  blog record start
  blog record stop and publish
  blog record stop and save

  align the webcam preview before recording
  # blog camera align
  blog camera align

  play or clear saved recordings
  # blog recordings play latest | blog recordings clear
  blog recordings play latest
  blog recordings clear
```

After `blog record stop and publish`, recorder cache files are auto-cleared.

## Config

Config path:

```text
~/.config/blog/config.json
```

Open it with:

```bash
blog config
```

Auto-created on first publish if missing. Template in repo: `template_config.json`

Default:

```json
{
  "publish": {
    "x": {
      "command": ["x", "post"],
      "text_args": ["{text}"],
      "media_args": ["with", "media", "{media}"]
    },
    "linkedin": {
      "command": ["linkedin", "post"],
      "text_args": ["{text}"],
      "media_args": ["with", "media", "{media}"]
    }
  }
}
```

Config forms:
- Simple: `"x": "x"` or `["x"]`, which appends text and media positionally.
- Structured: `command` + `text_args` + `media_args`, recommended when the downstream CLI uses connector words around media.

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
python main.py help
```
