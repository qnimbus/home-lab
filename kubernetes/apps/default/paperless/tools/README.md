# paperless metadata tools

`metadata.py` cleans up paperless's titles, document types, correspondents, tags and custom fields with the local LLM on the NAS (`llama-server`, see [`docker/nas/10-llama`](../../../../../docker/nas/10-llama/README.md)). Documents go from paperless to `llama.${DOMAIN_APP}` and nowhere else. The results land in `~/paperless-metadata` (mode `0700`), outside this repo: they hold document titles and names, and the repo is public.

Nothing here is deployed: Flux only applies `../app`.

## Setup

1. Create an API token in paperless (profile menu → My Profile → API Auth Token) and store it in 1Password as `API_TOKEN` on the `paperless` item.
2. Start the chat server if it isn't running: `just docker llama-start`.
3. Export the token for the shell you run the script from:

   ```bash
   export PAPERLESS_TOKEN=$(op read op://homelab/paperless/API_TOKEN)
   ```

Run every step as `kubernetes/apps/default/paperless/tools/metadata.py <step>` (it runs through `uv`).

## Steps

| Step        | What it does                                                                                                                            | Writes                                      |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| `inventory` | Exports types, tags, correspondents, storage paths and custom fields, with document counts. No document content.                        | `inventory.json`                            |
| `summarize` | The LLM describes each document: one-line summary, kind, sender, life domains, language. Newest first.                                  | `summaries.jsonl`                           |
| `propose`   | Turns the summaries into a proposed taxonomy: at most 25 types, 15 domain tags, advice per existing tag, and correspondent name groups. | `taxonomy.proposed.yaml`, `proposal.md`     |
| (you)       | Edit the proposal and save it as `taxonomy.yaml`. That file is the convention.                                                          |                                             |
| `suggest`   | Per document: title, one type, correspondent, 1–4 domain tags and the custom fields, constrained to `taxonomy.yaml`.                    | `suggestions.csv`                           |
| (you)       | Review the CSV in a spreadsheet and edit cells. Rows with `x` in `apply` get written; `suggest` pre-marks the confident ones.           |                                             |
| `apply`     | Writes the marked rows. A dry run unless `--yes`.                                                                                       | `apply-journal.jsonl`, changes in paperless |
| `undo`      | Restores what an apply run changed. A dry run unless `--yes`.                                                                           | changes in paperless                        |
| `tag`       | Puts a temporary tag (`Redo OCR` unless `--name`) on `--bad-ocr` or `--ids` documents; `--remove` deletes it. A dry run unless `--yes`. | a tag in paperless                          |

**Pre-marked rows.** `suggest` puts `x` in `apply` when the model's `confidence` is `hoog` and the correspondent needs no check (`correspondent_status` isn't `nieuw: controleren` or `controleren: …`). Review the empty rows, and spot-check the marked ones: clear the `x` on any you don't want. `suggest --no-mark` leaves every cell empty.

`summarize` and `suggest` take `--limit N`, `--query '<paperless search>'` and `--ids 1,2,3`, and resume where they stopped: run them again to continue. `summarize --redo` describes documents again; the newest summary of a document wins.

Both go newest first. For the taxonomy sample, use `summarize --random --limit 1000`: newest first would leave out the kinds of documents and senders that only older documents have. Each `--random` run skips documents that already have a summary, so running it again adds another random batch.

`propose` can run again after more summaries. Once `taxonomy.yaml` exists, it builds on that file:

- **Kept unchanged:** its types, domain tags and correspondent groups, in their order, and every other setting.
- **New types and domains** are added at the end.
- **A new spelling** becomes an alias of the group it resembles.
- **Tag advice** covers only tags the file doesn't mention yet.
- **`ignore`:** names listed there are never proposed again.

`proposal.md` lists what is new. `propose` still writes only `taxonomy.proposed.yaml`: compare it with `diff taxonomy.yaml taxonomy.proposed.yaml` and copy over what you want.

## What the LLM sees

The first 3000 (`summarize`) or 6000 (`suggest`) characters of paperless's OCR text, and the original filename, flagged as often meaningless (scanner and download names). Never the PDF's own metadata: on a home scan its author and producer are the printer.

`suggest` also sees the document's current title, type, correspondent and tags, described as possibly correct and useful but possibly stale, incomplete or wrong. The model keeps what the content confirms or makes plausible and drops what contradicts it; when the content itself is unclear, the current values may decide, and it answers `confidence: laag` if only they support its answer. `--ignore-current` leaves them out. `summarize` never sees them, so the taxonomy proposal rests on the documents alone; `propose` sees only the names and counts of the existing types and tags, to reuse names that fit.

The sender (`afzender`, `correspondent`) is the organisation that wrote or issued the document: the letterhead, or for a licence, card, diploma or certificate the issuing body. Never the holder, recipient or someone who only signs. When that isn't clear, it's left empty rather than guessed.

`summarize` also rates the OCR (`goed`, `matig`, `slecht`): the model's impression of the extracted text, not a measurement. It never sees the scan, and a page of numbers or tables can look worse than it is. `proposal.md` lists the IDs rated `slecht`. Reprocessing them only helps with paperless's OCR mode set to `redo` (or `force`): in the default `auto`, a PDF that already has more than 50 characters of text, such as a printer's own OCR layer, is never OCR'd again. paperless's document list can't filter on a list of IDs (and full-text search treats `id:` as a word), so `tag --bad-ocr --yes` tags them `Redo OCR`, without matching, so paperless never adds it to new documents. Filter on that tag, bulk edit → Reprocess, run `summarize --redo --ids <ids>` once paperless has finished, then `tag --remove --yes`.

## Timing

About 6–7 seconds per document on the NAS, so a pass over every document takes most of a night. The proposal doesn't need every document: `summarize --random --limit 1000` is a good sample. Run `suggest` in batches and review each one. paperless's own AI suggestions keep working meanwhile: the server handles one request at a time, so they wait for one script request at most.

## What `apply` does to a document

- **Every text value is one line**, in the CSV and in paperless: `suggest` and `apply` both turn newlines into spaces, drop control characters, and strip a leading `=`, `+`, `-` or `@`, which a spreadsheet would run as a formula.
- **title, type and correspondent** are set to the CSV's values. A missing type, tag, correspondent or custom field is created, with paperless's Auto matching so it learns from the documents it is assigned to.
- **tags**: only the tags in `keep_tags` (`Inbox`, people) and `label_tags` stay; every other tag, nonsense ones included, is replaced by the CSV's domain and label tags. `remove_tags` always go, even when also in `keep_tags`. With `keep_tags` empty, apply only replaces domain tags and removes `remove_tags`, and every other tag stays. Both runs print each document's tag changes (`tags -[removed] +[added]`): read the dry run before `--yes`.
- **custom fields** from the CSV are set; the document's other fields stay.
- **storage path**: removed when `clear_storage_paths: true`, so the archive layout below applies to the document.
- paperless renames the file to match `PAPERLESS_FILENAME_FORMAT`, which uses the title and correspondent.
- **a document an earlier run already changed is skipped**, unless that run was undone: `suggest` appends every batch to the same CSV, so the `x` marks of earlier batches are still there, and writing them again would overwrite whatever you fixed in paperless since. `--reapply` writes them anyway, for a row you edited after applying it.
- **`--limit N`** writes only the first N marked rows, in CSV order. Written rows are skipped next time, so the next run continues with the rest: a way to try a few documents and check them in paperless first. With `--reapply`, a limited run starts at the top again.

## Undo and backups

Before it changes a document, `apply` records the document's old title, type, correspondent, tags and custom fields in `apply-journal.jsonl`. `undo` (the last run), `undo --run <id>` or `undo --all` puts them back and deletes what the run created, unless another document uses it by then. paperless renames the files back.

The journal lives in `~/paperless-metadata` only. Take a database backup before the first real `apply` anyway: `just k8s db-backup default paperless`.

## `taxonomy.yaml`

```yaml
title_language: nl # or "document": the title in the document's own language
title_rule: Wat het document is, gevolgd door onderwerp of periode. Geen afzender of datum. Hoogstens 60 tekens.
document_types:
  - { name: Factuur, description: Een verzoek om te betalen voor geleverde goederen of diensten }
tags:
  - { name: Wonen, description: Het huis, energie, water, gemeentelijke belastingen }
label_tags: # optional: suggest adds them where they clearly apply; never an archive folder
  - {
      name: Garantie,
      description: Een garantiebewijs of aankoopbewijs van een product met garantie,
    }
keep_tags: [Inbox] # the only tags apply leaves on a document, next to the domain and label tags
remove_tags: [Archived] # removed from every document that apply touches
custom_fields:
  - { name: Bedrag, type: monetary, description: Te betalen of ontvangen bedrag }
summary_field: Samenvatting # optional: a one-line summary per document
ocr_field: OCR-kwaliteit # optional: goed, matig or slecht
clear_storage_paths: true # apply removes each document's storage path (see Archive layout)
layout_fallback: Overig # the folder for a document without a domain tag
layout_undated_types: [Identificatie, Akte] # no year folder (see Archive layout)
layout_reference_types: [Handleiding] # filed under layout_reference_folder, without a date
layout_reference_folder: Naslag
correspondents:
  - { name: Voorbeeld Energie, aliases: [Voorbeeld Energie B.V.] }
ignore: # names propose never suggests again
  correspondents: [Voorbeeld Blog]
  tags: [Veld]
  document_types: []
```

Custom field types: `string`, `date`, `monetary`, `integer`.

**Label tags** mark a property, not a subject: a warranty, a licence code. `suggest` adds one only where its description clearly applies, in the CSV's `tags` column after the domain tags. `apply` keeps a label tag a document already has. `layout` ignores label tags, so they never become a folder, and `propose` never offers them as a domain.

**Summary and OCR quality.** With `summary_field` set, `suggest` writes a one-line Dutch summary of at most 128 characters per document (paperless's plain text field limit), before it classifies the document; with `ocr_field` set, it rates the OCR. Both land in the CSV's `summary` and `ocr` columns, to review and edit like the rest, and `apply` writes them to those custom fields, creating them if missing: the summary as Text, OCR quality as a Select with the options `goed`, `matig` and `slecht`. A field you created yourself keeps its type (Long Text works too). The summary shows on the document and as a list column, but paperless's plain search doesn't cover custom fields: only `custom_fields.value:<word>` finds it. It is the model's reading of the document at that moment, so it can be wrong and doesn't update when the document changes.

**Correspondents.** `propose` groups spellings that differ only in case, punctuation or legal form (B.V., N.V.), and leaves out a sender paperless doesn't know unless at least two documents name it (`--min-sender-count`): one-off names are mostly misreads. In `suggest`, the model first writes the sender as the document names it, then picks from paperless's correspondents plus this list, or answers `(nieuw)` or `(onbekend)`. A list nudges a model to pick something, so the script checks the pick resembles what it wrote (shared word, initials such as KLM, similar spelling). The CSV's `correspondent_status`:

| Status                                            | `correspondent` cell                                                    |
| ------------------------------------------------- | ----------------------------------------------------------------------- |
| `bestaand`, `alias van X`                         | an existing correspondent                                               |
| `nieuw (uit taxonomy)`                            | a name from this list that paperless doesn't have yet; apply creates it |
| `nieuw: controleren`                              | a name nobody knows yet; apply creates it, so check the spelling        |
| `controleren: document noemt 'A', lijst koos 'B'` | empty: fill in the right one, or leave it                               |
| `onbekend`                                        | empty                                                                   |

An empty cell makes apply keep the document's current correspondent. With more than 1500 correspondents there is no list, and the written name is matched instead.

## Archive layout

paperless names the files on disk (`/mnt/archive/media`, originals and archive copies alike) from `PAPERLESS_FILENAME_FORMAT`. `layout` turns `taxonomy.yaml` into a format that files every document as

```text
<domain>/<type>/<year>/<date> <sender> - <title> - <id>.pdf
Wonen/Factuur/2026/2026-11-03 Energiebedrijf - Jaarafrekening stroom en gas - 1234.pdf
```

- **The folder is the document's domain tag.** With several, the first one in `taxonomy.yaml`'s `tags` order wins, so list specific domains (Wonen, Auto) above general ones (Financiën). No domain tag: `layout_fallback`.
- **No type or sender:** that part drops out (`Overig/2026/2026-11-10 - Notitie - 1235.pdf`).
- **`layout_undated_types` skip the year folder** (`Persoonlijk/Identificatie/2024-01-10 Gemeente - Paspoort - 301.pdf`): a passport or deed is looked up by what it is, not by when it came in. The date still leads the file name, so they sort in time order.
- **`layout_reference_types` go under `layout_reference_folder`** (default `Naslag`), outside the domains and without a date: `<folder>/<type>/<sender> - <title> - <id>.pdf`, as in `Naslag/Handleiding/Fabrikant - Vaatwasser - 77.pdf`. For a manual or recipe the brand and product matter, not when it was scanned.
- **A type can be in only one of the two lists**, and must be in `document_types`. The format holds these type names as fixed text, like the domain tags: after renaming such a type, run `layout` again.
- **The sender is in the file name, not a folder:** most senders have a handful of documents, and a rename or merge would move all of them.
- **The document ID ends the name:** it keeps two documents with the same date, sender and title apart, and leads from a file (in a backup, say) to the document in paperless, whose URL holds the same number.
- **A storage path overrides the format.** `clear_storage_paths: true` makes `apply` remove them; delete the unused storage paths in paperless afterwards.

`layout` needs only `taxonomy.yaml`. It prints the plain format (paste it into a storage path's **Test** in paperless to try it on a document), the version escaped for the HelmRelease, and, with a `suggestions.csv`, how many documents would land in each folder.

To switch:

1. Run `layout` and put its escaped line in `kubernetes/apps/default/paperless/app/helmrelease.yaml` as `PAPERLESS_FILENAME_FORMAT`. It holds domain and type names only.
2. Merge. paperless uses the format for every document saved from then on.
3. Move the existing files: `document_renamer` in the `app` container. It renames on disk only; nothing in the database changes but the file name.

Changing the domain list or its order later means running `layout` and these steps again.

**The format holds the domain tag names as fixed text.** Renaming or deleting a domain tag in paperless itself, without updating `taxonomy.yaml` and the format, silently files its documents under `layout_fallback`. Rename in `taxonomy.yaml` and paperless together, then rerun `layout` and update the HelmRelease. And since the folder follows the tags, adding or removing a domain tag on a document moves its file: that is the layout working, not a fault.
