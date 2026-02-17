# AI Nested `data.yaml` Spec

This document specifies how an AI agent should generate note data for this repository.

## Scope

The AI writes nested `data.yaml` files under a crawl root.  
The build system discovers those files, derives tags from folder structure, and manages GUID identity in one root `guid-map.yaml`.

## Required Root Files

At `--base` (deck-set root), the following must exist:

- `models.yaml`: model definitions (`id`, fields, templates, metadata).
- `deck.json`: deck defaults.
- `config.json`: deck config defaults.
- `decks/<DeckName>/build.json`: per-deck UUID/name config and enabled models.
- `ankidm.yaml`: crawl + path-tag configuration.

The following is generated/maintained by tooling:

- `guid-map.yaml`: stable note identity to GUID map.

## `ankidm.yaml` Schema

`ankidm.yaml` controls crawl behavior and path-derived tags.

```yaml
crawl:
  root: /absolute/or/relative/path
  include: ["**/data.yaml"]
  exclude: [".anki/**", "build/**"]
path_tags:
  levels:
    - name: subject
      index: 0
      emit_value_tag: true
      value_tag_prefix: sub
    - name: src
      index: 1
      emit_value_tag: true
      value_tag_prefix: src
    - name: ch_lec
      index: 2
      tag_name: chapter:lecture
      emit_value_tag: false
      value_template: "{src}::{ch_lec}"
  include_other_segments: true
```

### `crawl` fields

- `root` (required): directory where crawl starts.
  - If relative, it is resolved relative to `--base`.
- `include` (optional): glob(s) to include; default `["**/data.yaml"]`.
- `exclude` (optional): glob(s) to exclude, matched against paths relative to `crawl.root`.

### `path_tags` fields

- `levels` (required when `path_tags` is present): list of level rules.
- `include_other_segments` (optional, default `true`): add unmapped path segments as tags.

Each level rule:

- `name` (required): variable name for templates.
- `index` (required): 0-based segment index from path relative to `crawl.root`.
- `emit_value_tag` (optional): emit tag from segment itself.
  - Default: `true` unless `tag_name` is set.
- `value_tag_prefix` (optional): if set, emitted value tag becomes `prefix::value`.
- `tag_name` (optional): emit additional hierarchical tag `tag_name::formatted-value`.
- `value_template` (optional, default `"{value}"`): template for tag value.
  - Can reference any level `name` plus `value`.

## Nested `data.yaml` Schema

Every crawled file must be an object with `notes` list:

```yaml
notes:
  - id: unique-note-id
    model: basic
    fields:
      Front: Question
      Back: Answer
    fields_by_lang:
      fr:
        Front: Question (FR)
        Back: Reponse (FR)
    tags: [topic::example]
```

### Note fields

- `id` (recommended): stable note identifier string.
  - Use a slug-like stable value (for example, `topic-proof-001`).
  - Required for stable identity across reordering in a file.
- `model` (required): model ID from root `models.yaml` `models[*].id`.
- `fields` (required): object mapping model field names to values.
  - Must include every required field used by that model.
- `fields_by_lang` (optional): localized overrides by language code.
  - Shape: `{ "<lang>": { "<fieldName>": "<localized value>" } }`
- `tags` (optional): list of strings or space-separated string.

Unknown additional keys are ignored by the builder.

## GUID Tracking and Determinism

GUIDs are not stored in note rows. They are stored in root `guid-map.yaml`.

`guid-map.yaml` key format:

- `id:<relative-data-yaml-path>#<id>` when note `id` exists.
- `idx:<relative-data-yaml-path>#<row-index>` when `id` is omitted.

Behavior during `index`/`build`:

- New discovered note key -> deterministic GUID generated.
- Existing discovered key -> existing GUID reused.
- Deleted note key -> removed from `guid-map.yaml`.

Determinism guarantee:

- For a given note key, the assigned GUID is stable across runs.
- If `guid-map.yaml` is deleted and rebuilt, the same key gets the same GUID.

Identity caveat:

- If `id` is omitted, identity depends on row index. Reordering notes changes identity.
- If a note file is moved to a new folder, relative path changes identity key.

## Model Selection

AI must only emit `model` values defined in root `models.yaml`.

Typical imported model IDs:

- `basic`
- `cloze`

Do not assume field names; read `models.yaml` and match exactly.

## Basic Card Authoring

Use `model: basic` and provide fields expected by that model (commonly `Front`, `Back`):

```yaml
notes:
  - id: basic-topology-001
    model: basic
    fields:
      Front: What is a topological space?
      Back: A set together with a topology satisfying open-set axioms.
    tags: [topic::topology]
```

Card count is determined by the model templates in `models.yaml` (usually one card for `basic`).

## Cloze Card Authoring

Use `model: cloze` and put cloze markers in cloze-enabled field (commonly `Text`):

```yaml
notes:
  - id: cloze-choice-001
    model: cloze
    fields:
      Text: "{{c1::Axiom of choice}} is equivalent to {{c2::Zorn's lemma}}."
      Back Extra: "Frequently used in functional analysis."
    tags: [topic::settheory]
```

Cloze syntax:

- `{{c1::text}}`
- `{{c2::text}}`
- Optional hint: `{{c1::text::hint}}`

All cloze deletions in one note become sibling cards in Anki.

## MathJax and Equations

Use standard Anki MathJax delimiters inside field text:

- Inline math: `\( ... \)`
- Display math: `\[ ... \]`

Example:

```yaml
notes:
  - id: math-inline-001
    model: basic
    fields:
      Front: "State Parseval's identity."
      Back: "For \(f \in L^2\), \(\\|f\\|_2^2 = \\|\\hat f\\|_2^2\)."
```

Block equation example:

```yaml
notes:
  - id: math-block-001
    model: basic
    fields:
      Front: "Gaussian integral"
      Back: |
        \[
        \int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}
        \]
```

Math inside cloze:

```yaml
notes:
  - id: cloze-math-001
    model: cloze
    fields:
      Text: "Fourier inversion: {{c1::\(f(x)=\int_{\mathbb R}\hat f(\xi)e^{2\pi i x\xi}\,d\xi\)}}."
      Back Extra: ""
```

## YAML Authoring Rules for AI

- Output valid YAML object with top-level `notes`.
- Prefer block YAML style (not JSON-in-YAML style).
- Use `|` block scalars for multiline HTML/math-heavy content.
- If using double-quoted YAML strings with backslashes, escape as `\\`.
- Keep `id` stable forever once assigned.
- Never write `guid` in note rows.

## Path-Derived Tags

Tags are derived from the parent directory of each `data.yaml`, relative to `crawl.root`.

Example path:

- `math/infinitedimensionalanalysisbycharalambosaliprantis/oddsandends/data.yaml`

With level rules:

- `index 0` -> `subject=math`
- `index 1` -> `src=infinitedimensionalanalysisbycharalambosaliprantis`
- `index 2` -> `ch_lec=oddsandends`

Generated tag examples:

- `sub::math`
- `src::infinitedimensionalanalysisbycharalambosaliprantis`
- `chapter:lecture::infinitedimensionalanalysisbycharalambosaliprantis::oddsandends`

## Operational Commands

Re-sync GUID map from crawled notes:

```bash
poetry run anki-dm --base <deck-root> index
```

Rebuild CrowdAnki deck:

```bash
poetry run anki-dm --base <deck-root> build --build <output-dir>
```

