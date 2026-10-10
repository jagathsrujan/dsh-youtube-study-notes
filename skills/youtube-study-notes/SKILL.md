---
name: youtube-study-notes
description: Turn a YouTube link into final study notes by pulling the video's own captions, optionally reading on-screen content with a vision model, then pausing to collect the user's own voice or text notes and merging everything into one document. Use when the user shares a YouTube URL and wants notes, a summary, takeaways, or study material from it.
whenToUse: The user pastes a YouTube link and asks for notes, a summary, or study material; or asks to combine their own viewing notes with a video's content.
---

# YouTube → study notes

Produce **one markdown file** that merges three sources:

1. what the video *says* (YouTube's own caption track),
2. what the video *shows* (scene-sampled frames read by a vision model), and
3. what the user noticed, questioned, or cared about while watching.

All three together are the point. A transcript summary alone is a commodity; the user's
own observations woven into verified on-screen content are not. **Never skip step 4.**

## Pipeline

| # | Step | Gate |
|---|---|---|
| 1 | Fetch the video's own captions | no captions → stop and tell the user |
| 2 | Read through and outline | — |
| 3 | Visual pass — sample frames, read them with a vision model | skip if the video is talk-only |
| 4 | **Ask the user for their notes** | do not write notes before this |
| 5 | Merge all three sources | — |
| 6 | Save and report the path | — |

Paths below are **relative to this skill's base directory**, which the skill system
reports when the skill loads. Resolve them against that directory before use; do not
assume a fixed install location.

---

## 1. Fetch the transcript

Confirm `yt-dlp` exists: `command -v yt-dlp`. If missing, tell the user how to install it
(`brew install yt-dlp`, `pipx install yt-dlp`, or their platform's equivalent) and wait —
do not install packages unasked.

```bash
python3 scripts/yt_transcript.py "<URL>" --out "<workspace>/<video-slug>"
```

The script prints one JSON status line and exits:

- **exit 0** — success. Wrote `<out>/transcript.md` (timestamped, chaptered),
  `transcript.txt`, and `meta.json`. Read `caption_kind`: `manual` is human-written and
  reliable; `auto` is machine-generated with no punctuation and misheard proper nouns.
  **Say which one you got** — it changes how much the user should trust the wording.
- **exit 3** — the video publishes no captions at all. Stop. Do not guess at content and
  do not silently substitute anything else. Tell the user which video failed and offer a
  different video, or a local speech-to-text plugin for caption-less videos.
- **exit 2** — yt-dlp missing. **exit 4** — read or download failure; report verbatim.

Use `--lang hi,en` for non-English videos; this selects among existing caption tracks,
it does not translate. Reuse an existing `transcript.md` rather than re-downloading.

## 2. Read through and outline

Read `<out>/transcript.md` **in full** — walk long files with `offset`/`limit`; a partial
read produces notes with a hole in the middle.

Build a private outline: chapters, the arc of the argument, and the 3–6 ideas that carry
the video.

## 3. Visual pass

Run this when the video shows things it does not say — slides, code, diagrams, charts,
math, UI walkthroughs, demos. Skip it for talking-head interviews, podcasts, and
narrated essays; the frames would cost tokens and add nothing.

**a. Extract frames.** Scene-change detection picks one frame per shot:

```bash
python3 scripts/video_frames.py "<URL>" --out "<workspace>/<video-slug>/frames"
```

It prints a JSON status and writes `frames/frame_NNNN.jpg` plus `manifest.json`, which
maps every frame to its timestamp. `method` is `scene` when real cuts were found, or
`uniform` (evenly spaced) for continuously-animated video with no hard cuts — both are
valid; mention which if it affects coverage. For very long videos, use `--start` /
`--end` to cover only the section that matters, and `--max-frames` to bound cost.

**b. Read the frames.** First find out whether *this session's* model can see images —
do not assume, and do not hardcode a provider. Read a single frame with the `read_image`
tool and check the result:

- **It returns an image** → the session model is image-capable. Read the rest the same
  way, a few frames per step, and skip to (c).
- **It fails with `does not declare image input`** → the session model is text-only.
  Delegate to an image-capable model instead:

  Use the `workflow` tool, whose `agent()` accepts **independent `provider` and `model`
  overrides**. Ask the user which provider and model to use if you do not already know
  one that accepts images on their setup, and reuse that answer for the rest of the
  session rather than asking per frame. Batch 4–8 frames per agent and run them in
  parallel. Demand JSON only, one object per frame, each carrying its `time` so results
  re-anchor to the transcript:

  ```js
  const r = await parallel(frames.map(f => () =>
    agent(`Read ${f.path} with read_image. Return ONLY JSON:
           {"time":"${f.time}","text_on_screen":"<verbatim on-screen text>",
            "kind":"slide|code|diagram|chart|demo|other",
            "description":"<one factual sentence>"}`,
      { provider: "<provider>", model: "<image-capable model>" })));
  ```

- **It fails any other way** → report the error and continue with the transcript alone.

A model only accepts images if its configuration declares `input: [text, image]`. Many
model entries ship defaulting to `["text"]`, so a model whose *name* says "vision" may
still refuse images. If the user hits this, point them at the README's
"Enabling the visual pass" section; do not edit their profile configuration yourself.

Demand **verbatim** on-screen text — it is the highest-value output and the thing a
transcript can never give. If the vision step fails, say so plainly and continue with the
transcript; a failed visual pass must never sink the whole job.

**c. Fuse.** Line the on-screen evidence up against the transcript by timestamp. When a
slide's text and the narration disagree or the narration says "as you can see", the frame
is authoritative. Quote on-screen text exactly; it is often code, a formula, or a term
the caption track mangled. Treat small character-level vision errors as possible — a
period read as a hyphen, `1` as `l` — and flag anything load-bearing that is ambiguous.

## 4. Ask the user for their notes

**This is the step that makes this skill worth having. Do it before writing anything.**

Ask once, make it trivial to answer, then **end your turn and wait**. Do not produce
notes in the same turn — the user's answer is an input, not a nicety.

Make clear they can **type or dictate** (if their setup has voice input, the mic button
transcribes speech locally). Offer a skeleton so they can fill it in rather than compose:

> I've got the full transcript (18:40, 12 chapters) and I've read the on-screen content
> off 34 frames. Before I write this up — what did *you* take from it? Anything you noted
> while watching, anything that clicked, anything you want to make sure lands in the
> notes. Rough is fine.
>
> If it helps: the parts that mattered, questions you still have, and anything you
> disagreed with. You can type it or hit the mic and just talk.

Handle the replies:

- **Notes or questions given** → step 5, and answer anything the transcript can answer.
- **"No notes" / "just summarise it"** → proceed. Drop the user-attribution section
  rather than padding it. A valid answer, not a failure.
- **"Just give me the summary, don't ask"** → standing consent to skip the ask.
- **A question about the video** → answer with timestamps, then continue to step 5.

## 5. Merge

Follow `references/notes-template.md` for structure and its rules.

- Every claim traces to a transcript line, a frame, or a user note. Invent nothing.
- Compress, don't reformat. If a section reads like the transcript with markdown on it,
  rewrite it.
- Keep `[mm:ss]` anchors on anything the user may want to re-watch.
- Mark which lines came from the user, and mark on-screen-only content as such.
- Where a user note extends or contradicts the video, say so explicitly — that delta is
  usually the most valuable line in the file.
- Match register to content: tutorial → precision and code; talk → argument and framing;
  lecture → definitions and the worked example.

## 6. Save and report

Write `<out>/notes.md` beside the transcript, then tell the user the path and surface the
file. Lead your reply with the TL;DR, not with a description of what you did.

---

## Operational notes

- **yt-dlp breaks periodically** when YouTube changes. Symptom: exit 4 with an extractor
  error. Fix: upgrade yt-dlp.
- **Keep the transcript.** It is the evidence for every claim and lets the user re-run the
  merge without re-downloading.
- **Frame cost scales with length.** `--max-frames` caps it (default 48). A one-hour talk
  with slides is well served by 40–60 frames; a 10-minute code demo may need fewer but at
  higher resolution.
- **Personal study use.** Captions, frames, and derived notes are for the user's own
  reference; do not republish them.
- **Large videos** (2h+) exceed a single read. Walk the transcript in chunks and outline
  incrementally rather than truncating.
