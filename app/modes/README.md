# How to write a teaching mode

A mode is a single Markdown file in this directory. Drop a new `.md` file here, restart the server (or hit `POST /modes/reload` from the admin panel), and the mode appears in the admin panel and in `/modes`.

Loader: `app/mode_loader.py`. Prompt assembly: `ProfessorTux.build_messages` in `app/professor.py`.

> ⚠️ **Do not delete the six built-in modes** (`recall.md`, `recall_wrong.md`, `guided.md`, `guided_wrong.md`, `ctf.md`, `custom.md`). Their ids are wired into special-case logic in `app/professor.py` (recall hard rules, CTF override, wrong-turn rules, custom-mode persona bypass) and into the admin confirmation modals. You can freely **add** new mode files alongside them, and freely **delete or edit** any modes you yourself add — but removing the originals will leave dead references in the codebase.

## File layout

```markdown
---
id: my_mode
name: My Mode
icon: 🎯
color: "#22d3ee"
description: One-line summary shown in the admin mode card.
hint_message: Optional reminder shown to the student after each response.
---

System prompt body goes here. This is what shapes the model's behaviour
inside this mode. See "What the body should contain" below.
```

## Frontmatter fields

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | Unique slug. Used in the API, in URL params, and to match the special-case rules in `professor.py` (see "Reserved IDs"). |
| `name` | yes | Display label. Shown on the admin mode card and the student-page mode pill. |
| `icon` |  | Single emoji. Renders inside the mode card. |
| `color` |  | Hex string in quotes (e.g. `"#facc15"`). Drives the admin card glow/border and is meant to feed the student-page theme — see "Wiring the student page". |
| `description` |  | One sentence shown under the name in the admin card. |
| `hint_message` |  | Appended below each model response on the student page. Leave blank for none. |
| `student_message` |  | Empty-state intro copy shown on the student page before the first question. Falls back to `description`, then to a generic placeholder. |
| `student_title` |  | Headline shown above the empty-state copy (e.g. "Ask for explanation or walkthroughs"). Falls back to a generic "Ask Professor Tux". |
| `student_placeholder` |  | Placeholder text inside the chat input box. Falls back to a generic "Ask any cybersecurity question…". |
| `student_subtitle` |  | Tag-line shown after "Professor Tux" in the page header. Falls back to the mode `name`. |

The frontmatter parser is intentionally minimal (`_parse_frontmatter` in `mode_loader.py`): one `key: value` per line, quotes stripped, no nested YAML. Don't use multi-line strings.

## What the body should contain

The body is appended to the base persona as `"You are in {name}. {body}"` for every non-custom mode. Keep it short and behavioural:

- A one-line statement of what this mode does.
- A bulleted list of rules ("be concise", "use tables when comparing", "stay on cybersecurity").
- Optional `## Examples` block with `**Student:** … / **Response:** …` pairs separated by `---`. These become few-shot turns prepended to the conversation — useful for small models that imitate better than they instruction-follow.
- Optional `## Suggestions` block (parsed and stripped from the system prompt) for the four starter cards on the student empty state. One bullet per card:

  ```markdown
  ## Suggestions

  - **Web Security:** Teach me the main web application vulnerabilities with examples.
  - **Cryptography:** Explain hashing vs encryption.
  - **Binary / Pwn:** Walk me through network defense fundamentals step by step.
  - **Agent Handoff:** Walk me through the incident response lifecycle.
  ```

  Each line is `- **{card title}:** {prompt sent when the card is clicked}`. Up to four are typically shown; if the block is missing the empty state simply hides the suggestion grid.

### The 500-character rule cap

`_split_mode_prompt` joins all rule lines with single spaces and truncates at ~500 chars before injection. Long rule lists get cut off mid-sentence. To stay safe:

- Put your most important rules first.
- Keep each bullet under ~100 chars.
- If a rule is long, restate the gist tersely (e.g. "Use a compact Markdown table when comparing items (2-4 cols)" instead of a 300-char explanation).

Examples (`## Examples` section) are not subject to the cap — they're parsed separately and emitted as message turns.

## Reserved IDs

These IDs trigger extra logic in `app/professor.py` on top of your body:

| ID pattern | Extra behaviour |
|------------|-----------------|
| `recall`, `recall_*` | Adds `RECALL_MODE_HARD_RULES`. If the student's message looks like an MCQ, also adds `RECALL_MODE_MCQ_RULES`. Caps `max_tokens` at 96. |
| `*_wrong` | When the wrong-turn flag is set on a request, adds `WRONG_TURN_HARD_RULES` plus the recall- or guided-flavour wrong-turn rules. Bumps temperature to ≥1.05. |
| `ctf` | Adds `CTF_MODE_HARD_RULES` (lifts the "no exploit code" rule, enables `web_search` preloading + `ctf_agent_command`). Admin shows a confirmation modal before activating. |
| `custom` | **Skips the base persona, the mode marker line, all overrides, and few-shot examples.** Only topic / lecture context (if set) and the conversation history reach the model. Admin shows a confirmation modal. |

If your new mode's id matches one of these patterns, you inherit the extra rules — pick a fresh slug if you don't want them.

## Student-page wiring

Everything student-facing for a mode lives in this `.md` file — the student page reads it from the `/modes` API. Specifically:

- The mode's `color` drives the entire student-page palette via `applyModeAccent()` in `index.html` (accent, surface, border, and text vars are derived from the hex via CSS `color-mix()`). No per-mode CSS class needed.
- The four `student_*` frontmatter fields drive the mode pill, empty-state title, empty-state copy, composer placeholder, and brand subtitle. Generic fallbacks kick in for any field you leave blank.
- The `## Suggestions` body block drives the four starter cards.

That means **deleting a `.md` file removes a mode cleanly with no leftover code in `index.html`**. Likewise, a brand-new `.md` file shows up fully styled with no JS or CSS edits.

## Reloading

`GET /modes` re-scans this directory on every call, so dropping a new `.md` file is picked up the moment the admin page refreshes — no manual reload required.

- `POST /modes/reload` (admin auth) is still available as an explicit force-refresh and is what the *↻ Reload Modes* button calls.
- A full server restart also picks up changes.

## Minimal template

```markdown
---
id: example
name: Example Mode
icon: ✨
color: "#a78bfa"
description: One-sentence summary.
hint_message:
student_message: Short intro shown on the student empty state.
student_title: Headline above the intro.
student_placeholder: Placeholder text in the chat input.
student_subtitle: Short tag-line in the page header.
---

## Suggestions

- **Card one title:** Prompt sent when this card is clicked.
- **Card two title:** Another starter prompt.
- **Card three title:** And another.
- **Card four title:** And the last one.

State the teaching style in one line.

- Rule one.
- Rule two.
- Stay strictly on cybersecurity and adjacent topics.
```

That's enough to register a working mode. Add `## Examples` blocks if the model needs imitation cues; otherwise leave the body lean.
