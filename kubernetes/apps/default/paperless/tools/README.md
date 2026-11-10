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
| (you)       | Review the CSV in a spreadsheet, edit cells, and put `x` in `apply` for each row to write.                                              |                                             |
| `apply`     | Writes the marked rows. A dry run unless `--yes`.                                                                                       | `apply-journal.jsonl`, changes in paperless |
| `undo`      | Restores what an apply run changed. A dry run unless `--yes`.                                                                           | changes in paperless                        |

`summarize` and `suggest` take `--limit N`, `--query '<paperless search>'` and `--ids 1,2,3`, and resume where they stopped: run them again to continue. `summarize --redo` describes documents again; the newest summary of a document wins.

Both go newest first. For the taxonomy sample, use `summarize --random --limit 1000`: newest first would leave out the kinds of documents and senders that only older documents have. Each `--random` run skips documents that already have a summary, so running it again adds another random batch.

## What the LLM sees

The first 3000 (`summarize`) or 6000 (`suggest`) characters of paperless's OCR text, and the original filename, flagged as often meaningless (scanner and download names). Never the PDF's own metadata: on a home scan its author and producer are the printer.

`suggest` also sees the document's current title, type, correspondent and tags, described as possibly correct and useful but possibly stale, incomplete or wrong. The model keeps what the content confirms or makes plausible and drops what contradicts it; when the content itself is unclear, the current values may decide, and it answers `confidence: laag` if only they support its answer. `--ignore-current` leaves them out. `summarize` never sees them, so the taxonomy proposal rests on the documents alone; `propose` sees only the names and counts of the existing types and tags, to reuse names that fit.

The sender (`afzender`, `correspondent`) is the organisation that wrote or issued the document: the letterhead, or for a licence, card, diploma or certificate the issuing body. Never the holder, recipient or someone who only signs. When that isn't clear, it's left empty rather than guessed.

`summarize` also rates the OCR (`goed`, `matig`, `slecht`). `proposal.md` lists the IDs rated `slecht`: run Redo OCR on them in paperless (bulk edit), then `summarize --redo --ids <ids>`.

## Timing

About 6–7 seconds per document on the NAS, so a pass over every document takes most of a night. The proposal doesn't need every document: `summarize --random --limit 1000` is a good sample. Run `suggest` in batches and review each one. paperless's own AI suggestions keep working meanwhile: the server handles one request at a time, so they wait for one script request at most.

## What `apply` does to a document

- **title, type and correspondent** are set to the CSV's values. A missing type, tag, correspondent or custom field is created, with paperless's Auto matching so it learns from the documents it is assigned to.
- **tags**: only the tags in `keep_tags` (`Inbox`, people) stay; every other tag, nonsense ones included, is replaced by the CSV's domain tags. `remove_tags` always go, even when also in `keep_tags`. With `keep_tags` empty, apply only replaces domain tags and removes `remove_tags`, and every other tag stays. Both runs print each document's tag changes (`tags -[removed] +[added]`): read the dry run before `--yes`.
- **custom fields** from the CSV are set; the document's other fields stay.
- paperless renames the file to match `PAPERLESS_FILENAME_FORMAT`, which uses the title and correspondent.
- **a document an earlier run already changed is skipped**, unless that run was undone: `suggest` appends every batch to the same CSV, so the `x` marks of earlier batches are still there, and writing them again would overwrite whatever you fixed in paperless since. `--reapply` writes them anyway, for a row you edited after applying it.

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
keep_tags: [Inbox] # the only tags apply leaves on a document, next to the domain tags
remove_tags: [Archived] # removed from every document that apply touches
custom_fields:
  - { name: Bedrag, type: monetary, description: Te betalen of ontvangen bedrag }
summary_field: Samenvatting # optional: a one-line summary per document
ocr_field: OCR-kwaliteit # optional: goed, matig or slecht
correspondents:
  - { name: Voorbeeld Energie, aliases: [Voorbeeld Energie B.V.] }
```

Custom field types: `string`, `date`, `monetary`, `integer`.

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
