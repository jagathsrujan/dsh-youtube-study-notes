# dsh-youtube-study-notes

A [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (`dsh`) plugin that turns a YouTube link into study notes — and then gets *your* notes involved.

Give it a link. It pulls the video's own captions, samples the frames so it can read what was on screen, **stops and asks what you took from it**, and merges all three into one document.

The middle step is the point. Every other video-to-notes tool produces the same summary for everyone. This one writes the notes you'd have written, if you'd been taking notes.

## What it does

| Step | What happens |
|---|---|
| 1 | **Captions** — `yt-dlp` fetches the caption track YouTube already publishes. Human-written preferred, auto-generated as fallback. No ASR, no third-party transcript sites. |
| 2 | **Outline** — the timestamped transcript is read in full and outlined by chapter. |
| 3 | **Visual pass** *(optional)* — `ffmpeg` scene-change detection samples one frame per shot; a vision model reads the on-screen text. Catches slides, code, formulas and diagrams the narration never says out loud. |
| 4 | **Ask** — the agent stops and asks what *you* noticed, in your words. Type it or dictate it. |
| 5 | **Merge** — transcript + on-screen evidence + your observations, into one markdown file. |
| 6 | **Save** — `notes.md`, written beside the transcript so the evidence stays with it. |

## Install

```sh
dsh plugin --profile <your-profile> add dsh-youtube-study-notes
```

Restart the profile afterwards — bundle changes apply at boot.

Then trigger it either way:

```
/youtube-study-notes https://youtu.be/VIDEO_ID
```

or just ask in plain language ("get me notes from this video: …"). A link plus a request
for notes, a summary, or study material is enough.

> **Desktop clients:** the desktop app manages its own profile. Use its **Plugins → Add
> plugin** flow rather than the CLI, and enable the bundle when the install finishes.

## Requirements

The plugin ships no runtime code — its substance is the Skill, which drives local tools.
`dsh` does not install these for you:

| Tool | Role | Install |
|---|---|---|
| `python3` | runs the bundled scripts (standard library only) | `brew install python3` |
| `ffmpeg` / `ffprobe` | audio/video probing, scene detection, frame extraction | `brew install ffmpeg` |
| `yt-dlp` | caption listing and download | `brew install yt-dlp` |

The Skill detects missing tools, names them, and waits for your confirmation before
installing anything.

## Enabling the visual pass

Step 3 needs a model that accepts images, and **many model entries do not** — even ones
whose name says "vision". A model is only offered images if its configuration declares
`input: [text, image]`; entries otherwise default to `["text"]`, and the harness refuses
the image before attaching it with:

```
model "<provider>/<model>" does not declare image input
```

The Skill handles this: it tries `read_image` on a single frame first. If the session
model can see images, it reads the frames directly. If not, it delegates through the
`workflow` tool's per-agent `provider` / `model` override, and asks you once which
image-capable model to use.

To make a model explicitly image-capable, declare it in your profile's
`cordis.patch.yml` (the file your profile tells you to edit — not `cordis.yml`):

```yaml
- id: llm-pi-ai
  name: "@deepseek-ai/dsh-llm-pi-ai"
  config:
    providers:
      your-provider:
        # ...existing provider config...
        models:
          - id: "your-vision-model"
            name: "Your Vision Model"
            contextWindow: 200000
            input:
              - text
              - image
```

A profile with live reload picks this up without a restart.

> **Only declare this if the endpoint actually serves images.** Over-claiming admits an
> image the provider then rejects mid-turn, after the message is already durable. The
> declaration is not verified for you.

**If you skip all of this**, the plugin still works — it just produces transcript-only
notes, and says so rather than pretending it saw the screen.

## Limitations

- **Caption-less videos stop the run.** If a video publishes no caption track at all
  (not even auto-generated), step 1 reports which video failed and stops. Nothing is
  invented to fill the gap. Pair this with a local speech-to-text plugin if you need
  those covered.
- **Auto-generated captions are rough** — no punctuation, misheard proper nouns. The
  skill always reports which kind it got.
- **Vision reads can be wrong at the character level.** A period can read as a hyphen,
  `1` as `l`. Fine for prose, worth double-checking in code and formulas. The skill is
  instructed to flag anything load-bearing that looks ambiguous.
- **Frame sampling sees shots, not motion.** A diagram built up over one continuous shot
  yields a single frame.
- **Personal study use.** Captions, frames and notes are derived from someone else's
  work. Don't republish them.

## How it's built

```
package.json          declares dsh.bundle → cordis.patch.yml
cordis.patch.yml      inserts one @deepseek-ai/dsh-skill-filesystem row
lib/index.js          resolveSkillRoot() — resolves skills/ from the profile's own module identity
skills/youtube-study-notes/
  SKILL.md            the workflow
  scripts/            yt_transcript.py, video_frames.py
  references/         notes template and merge rules
```

The bundle mounts its `skills/` directory as an **isolated** provider
(`includeDefaultRoots: false`), so installing it contributes exactly one skill and
cannot shadow or reorder the ones you already have.

## License

MIT — see [LICENSE](LICENSE).
