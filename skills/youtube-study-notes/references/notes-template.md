# Final notes template

Use this skeleton for the merged deliverable. Drop sections that carry no content —
an empty heading is worse than a missing one.

---

```markdown
# <Video title>

**Source:** <url>
**Channel:** <channel> · **Length:** <duration> · **Notes written:** <YYYY-MM-DD>
**Evidence:** <manual|auto> captions, <N> words · <M> frames read (<scene|uniform>)

## TL;DR

<3–6 bullets. The whole video in thirty seconds. No preamble, no "this video discusses".>

## Key ideas

<The argument or curriculum of the video, in your own compression — not a transcript
reformat. One short paragraph per idea. Bold the load-bearing term.>

## <Chapter title>

<One section per chapter that carries real content. Chronological. Keep the
`[mm:ss]` anchor for anything the user may want to re-watch — this is the single
most useful thing a timestamped transcript buys you.

Where a frame showed something the narration did not say, put it here and mark it
as on-screen: code, a formula, a parameter value, a diagram's labels. **Quote
on-screen text verbatim** — it is usually the one place a term, number, or symbol
survives un-mangled, and the caption track is exactly where it gets garbled.>

## Answers to your questions

<Only if the user asked something. Answer directly from the transcript, cite the
timestamp, and say plainly when the video does not actually cover it.>

## Your observations, integrated

<Where the user's own notes connect to, extend, or contradict the video. Mark
clearly what came from them. If they flagged something the video skips, say so —
that gap is usually the most valuable line in the document.>

## Quick reference

<The compressed artifact: formulas, commands, terms, a Mermaid map for long or
structural content. Whatever the user would pin above their desk.>

## Open threads

<What the video raised but did not resolve. Skip if genuinely nothing.>
```

---

## Rules

- **Never invent content.** Every claim traces to a transcript line, a frame, or a user note.
- **Prefer the frame when they conflict.** Narration simplifies; the slide is what was
  actually claimed. When a frame could not be read, or a section had no frames, say so
  rather than filling the gap from the narration alone.
- **Timestamps anchor, they do not decorate.** `[4:32]` on a claim the user might
  want to verify; not on every sentence.
- **Compress, do not transcribe.** If a section reads like the transcript with
  markdown sprinkled on it, it has failed.
- **Attribute the merge.** The user must be able to tell which lines are theirs.
- **Match the register to the content** — a technical tutorial wants precision and
  code; a talk wants the argument and the framing; a lecture wants definitions and
  the worked example.
