# Agent instructions

Entry point for any coding agent working in this repo. Tracked in git, so it
reaches every clone. `CLAUDE.md` is gitignored and local to each machine.

## Where things are

| Topic | File |
|---|---|
| Writing conventions | `docs/agents/writing.md` (canonical). Mirrored below. |
| Issue tracker operations | `docs/agents/issue-tracker.md` |
| Triage labels | `docs/agents/triage-labels.md` |
| Domain docs and vocabulary | `docs/agents/domain.md` |
| Product scope | `PRD.md` |
| What is built and what is open | `FLEDGE_ROADMAP.md` |
| Model provenance and measured accuracy | `machine_learning/MODELS.md` |
| Architecture and coding conventions | `CLAUDE.md`, local only |

## Writing conventions

Mirrored from `docs/agents/writing.md`. That file is canonical. Change it there
first.

These rules apply to every word written for a human to read. Chat replies, GitHub
issue bodies and comments, pull request text, commit messages, docs, and code
comments. They override the default style of any skill, including `/wayfinder`,
`/grilling`, and `/research`.

They do not apply to code identifiers, quoted material, command output, or
existing text nobody asked to change.

The rules merge two sources. ASD-STE100 Simplified Technical English supplies the
sentence discipline. Poteto's `unslop` supplies the pattern list and the voice
guidance. Take the STE rules, not the STE controlled vocabulary. Domain terms stay.

### Sentences

- One idea per sentence. Split any sentence that makes the reader backtrack.
- About 20 words per sentence for instructions. About 25 for explanation.
- Six sentences per paragraph at most.
- Active voice. Name the actor. Write "the worker drains the queue", not "the
  queue is drained". Passive is fine only when the actor is unknown.
- Simple tenses. No stacked participles.
- Three words at most in a noun cluster.

### Punctuation

- No em dashes. End the sentence or use a comma. Do not substitute parentheses,
  en dashes, or a hyphen standing in for a dash.
- Colons introduce a list or an example. Never use one as a mid-sentence connector.
- Straight quotes, not curly.

### Words

- Use the plain word. Use, not utilize. Help, not facilitate. Many, not numerous.
- One term per thing. Never cycle synonyms for variety.
- No abstract metaphor nouns. Substrate, wedge, vector, nexus, primitive, harness,
  surface, bedrock, scaffolding, north star, flywheel, load-bearing. Name the
  mechanism instead.
- No AI vocabulary. Additionally, crucial, delve, enhance, fostering, garner,
  intricate, landscape, pivotal, showcase, tapestry, testament, underscore, vibrant.
- Say "is" or "has". Not "serves as", "stands as", "boasts", "features".
- Cut adverbs. An adverb propping up a weak verb means the verb is wrong. Give the
  number instead of "significantly faster".
- Cut filler. "In order to" is "to". Delete "it is important to note that".
- Cut stacked hedges. "Could potentially possibly" is "may".
- No "not just X, but Y". State the point.

### Shape

- Answer first. Reasons second.
- Tables and lists carry structure. Prose carries argument.
- Sentence case headings. No decorative emoji.
- Do not bold every proper noun or acronym.
- A bold label that restates the line is a tell. A bold lead-in that names the item
  and is followed by new detail is fine.
- Say what a thing does, not how it feels. Name the mechanism, the file, or the
  number. If a sentence would fit another project unchanged, cut it.

### Voice

- Have an opinion. React to the facts instead of listing both sides evenly.
- Be specific. Name the number, the file, the failure mode.
- No chatbot phrases, no sycophancy, no generic conclusions.

### When the two sources conflict

STE wants uniform short sentences. `unslop` wants varied rhythm and human voice.

| Artifact | Which wins |
|---|---|
| Issues, specs, decision records, commit messages, docs | STE discipline. Short and uniform. |
| Chat replies, and any text that argues a position | Vary sentence length. Keep every word and punctuation rule. |

Both always share active voice, one idea per sentence, plain words, no em dashes,
and no filler.

### Two points specific to this repo

- There is no `CONTEXT.md` yet. Until `/domain-modeling` creates one, take terms
  from `PRD.md`, `MODELS.md`, and `CLAUDE.md`. Do not invent a synonym for a term
  the code already uses. Say "tier", "escalation", "sighting", "visit", "capture",
  and "device" the way the code says them.
- Wayfinder tickets name each other constantly. Write the ticket title as the link
  text. A bare `#42` is unreadable in a list of twenty.

### Before sending

Ask one question: what makes this look machine written? Fix what turns up. The
usual answers are em dashes, a sentence over 40 words, and a metaphor standing
where a mechanism belongs.
