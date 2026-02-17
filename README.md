# **ankidmpy**

**ankidmpy** ( pronounced "anki-dumpy" ) is a straightforward port of [anki-dm](https://github.com/OnkelTem/anki-dm)    to `python`.   The original **anki-dm** is written in `PHP` and is a tool to work with the [CrowdAnki plugin](https://github.com/Stvad/CrowdAnki) for the [Anki](https://apps.ankiweb.net/) spaced repetition memory app to facilitate collaborative building of flash card decks. 

## Overview
**CrowdAnki** also aims to facilitate collaboration by extracting all the details of an Anki deck into a single json file for easier editing. Building on this, **ankidmpy** splits this into editable files, including YAML files for note data and model definitions.

Reversing the process, you can *build* a **CrowdAnki** file from these edited files and in turn *import* these files back into **Anki** with the plug-in to be used for spaced repetition memorization.

## Usage
The usage is nearly identical to the original **anki-dm** with only slight differences to accommodate standard arg parsing in `python`.

```sh
$ python -m ankidmpy --help
usage: anki-dm [-h] [--base BASE] [--templates]
               {init,import,build,copy,index} ...

This tool disassembles CrowdAnki decks into collections of files and
directories which are easy to maintain. It then allows you to can create
variants of your deck via combining fields, templates and data that you really
need. You can also use this tool to create translations of your deck by
creating localized columns in data files.

positional arguments:
  {init,import,build,copy,index}
    init                Create a new deck from a template.
    import              Import a CrowdAnki deck to Anki-dm format
    build               Build Anki-dm deck into CrowdAnki format
    copy                Make reindexed copy of Anki-dm deck.
    index               Set guids for rows missing them.

optional arguments:
  -h, --help            show this help message and exit
  --base BASE           Path to the deck set directory. [Default: src]
  --templates           List all available templates.
$
```
There are several sub-commands which each take their own options.   The `--base` switch applies to each of these sub-commands and must be supplied before the sub-command.   This switch indicates the root directory to use when looking for or generating new files.

The `--templates` switch simply lists the sample **CrowdAnki** decks which can be built upon to generate new decks and doesn't require a sub-command.

Help for the sub-commands can be found by applying `--help` to the sub-command:

```sh
$ python -m ankidmpy init --help
usage: anki-dm init [-h] [--deck DECK] template

positional arguments:
  template     Template to use when creating the deck set.

optional arguments:
  -h, --help   show this help message and exit
  --deck DECK  Name of the default deck of the deck set being created. If not
               provided, then the original deck/template name will be used.
$
```

## Recursive Folder Tags
`build` crawls `data.yaml` files recursively and derives tags from the folder path of each `data.yaml`. You do not need to store a `path` key in each note.

### 1) Add `ankidm.yaml`
Create `/path/to/deck-set/ankidm.yaml`:

```yaml
crawl:
  root: /Users/josdan/stuff/development/Notes
  include: ["**/data.yaml"]
  exclude: [".anki/**", "build/**"]
path_tags:
  levels:
    - name: subject
      index: 0
      emit_value_tag: true
    - name: src
      index: 1
      emit_value_tag: true
      value_tag_prefix: src
    - name: ch_lec
      index: 2
      tag_name: chapter:lecture
      value_template: "{src}::{ch_lec}"
  include_other_segments: true
```

Each entry in `levels` supports:
- `name`: level variable name used by templates (for example: `subject`, `src`, `ch_lec`)
- `index`: 0-based folder depth relative to `crawl.root`
- `emit_value_tag` (optional): add the folder name itself as a tag
- `value_tag_prefix` (optional): if set, emit `prefix::value` instead of just `value`
- `tag_name` (optional): emit an additional hierarchical tag with this prefix
- `value_template` (optional): template for `tag_name`, with access to all level names and `{value}`

### 2) Put `data.yaml` in nested folders
Example files:

- `/Users/josdan/stuff/development/Notes/math/infinitedimensionalanalysisbycharalambosaliprantis/oddsandends/data.yaml`
- `/Users/josdan/stuff/development/Notes/math/geometricanatomyfredricschuller/topologicalspaceheavilyusedinvariant/data.yaml`

### 3) Build
```sh
$ python -m ankidmpy --base /path/to/deck-set build
```

Tags are derived from each `data.yaml` parent directory.

## Data Format
The deck-set format uses YAML for notes and model definitions:

- `models.yaml`: model metadata, fields, templates, css, and model UUIDs.
- `data.yaml`: notes (`model`, `fields`, `tags`) and optional localization via `fields_by_lang`.
- `guid-map.yaml`: note identity map used for GUID stability (`guid` is no longer stored inside notes).
- `ankidm.yaml`: crawl + path tag configuration.

`guid-map.yaml` is a single map at `--base`, keyed by crawled note identity:
- `id:<relative-data-yaml-path>#<note-id>` when `id` is present
- `idx:<relative-data-yaml-path>#<row-index>` otherwise

During `index` or `build`, the map is synchronized to discovered notes:
- new notes get deterministic GUIDs
- deleted notes are pruned from `guid-map.yaml`

### `models.yaml` example
```yaml
models:
  - id: cloze
    name: Cloze
    uuid: 11111111-1111-1111-1111-111111111111
    info:
      type: 1
      latexPost: \\end{document}
      latexPre: \\documentclass[12pt]{article}
      vers: []
    fields: [Text, Extra]
    templates:
      - name: Cloze
        qfmt: "{{cloze:Text}}"
        afmt: "{{cloze:Text}}<br>{{Extra}}"
        bqfmt: ""
        bafmt: ""
        did: null
    css: ".card { font-family: arial; }"
```

### `data.yaml` example
```yaml
notes:
  - id: axiom-of-choice-1
    model: cloze
    fields:
      Text: "{{c1::Axiom of choice}} statement"
      Extra: details
    fields_by_lang:
      fr:
        Text: "{{c1::Axiome du choix}}"
    tags: [math, settheory]
```

`index` now reindexes `guid-map.yaml` across all crawled `data.yaml` files.
Use optional `id` to keep GUID mapping stable if you reorder notes in a file. If `id` is omitted, mapping falls back to file path + note index.

For a complete AI authoring contract for nested `data.yaml` generation (including basic/cloze/math examples), see `AI_DATA_SPEC.md`.

## Multi-Model Support
`import` now supports CrowdAnki decks with multiple note models (for example, both `Cloze` and `Basic`) and preserves each note's model identity in `data.yaml`.

## Building
**ankidmpy** is written in Python and requires `PyYAML` for reading and writing YAML deck data.

You can run **ankidmpy** with `python -m ankidmpy` by pointing your `PYTHONPATH` at the `src` directory or you can use [poetry](https://python-poetry.org/docs/) to build a wheel distribution like so:

```sh
$ poetry install
$ poetry build
```
Once you run `poetry install` you can also run **ankidmpy** using the **poetry** script like so:

```sh
$ poetry run anki-dm --help
```
See the **poetry** documentation for more details.
