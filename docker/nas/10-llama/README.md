# llama

Two [llama.cpp](https://github.com/ggml-org/llama.cpp) servers on the NAS's Radeon 890M (Vulkan), each with an OpenAI-compatible API behind Traefik:

| Service           | Address                      | Presets                                                                |
| ----------------- | ---------------------------- | ---------------------------------------------------------------------- |
| `llama-server`    | `https://llama.vwn.app`      | `config/models.ini`: chat models, one loaded at a time                 |
| `llama-embedding` | `https://embeddings.vwn.app` | `config/models.embedding.ini`: harrier-oss-v1-0.6b, last-token pooling |

The model files live on the NAS in `/mnt/tank/AI/models`, mounted read-only at `/models`. They are not in Git: download a new one there before adding a preset that points at it.

## Always on, and on demand

- **`llama-embedding` always runs.** paperless embeds every new document and rebuilds its index nightly, so the endpoint has to be up. doco-cd starts it on every deploy, and `restart: unless-stopped` brings it back after a reboot.
- **`llama-server` is on demand.** It carries `cd.doco.deployment.autostart: "false"`: doco-cd creates its container but doesn't start it, and leaves it stopped when it redeploys. Start and stop it by hand:

  ```bash
  just docker llama-start
  just docker llama-stop
  just docker llama-status   # both containers
  ```

  If it was running, `restart: unless-stopped` brings it back after a NAS reboot; a stopped one stays stopped. While it is stopped, Traefik has no route for it: it only routes running containers.

## Gotchas

- **They share the GPU and the system RAM** (the 890M has no memory of its own). Vulkan sees about 42 GB: a chat model (17–22 GB at Q4) with its 32K context and the embedding model fit together, two chat models barely; `--models-max 1` keeps it to one.
- **Qwen3.8-27B is dense**: every token reads all 27B weights, against 3B for Qwen3.6-35B-A3B, so on this shared-memory GPU it generates several times slower. Qwen3.6-35B-A3B stays the default; the 27B is there to compare quality.
- **Sampling defaults are Qwen's recommendations**, set per preset: non-thinking temp 0.7, top-p 0.8, presence-penalty 1.5; thinking temp 1.0, top-p 0.95; top-k 20 and min-p 0 for both. A client that sends its own sampling values overrides them.
- **`Qwen3.6-35B-A3B` has no presence-penalty**: paperless (`PAPERLESS_AI_LLM_MODEL`) uses it for structured suggestions (titles, tags, fields), which repeat quotes, brackets and field names, and a penalty pushes the model away from tokens it has already written.
- **`XDG_CACHE_HOME: /tmp/.cache`**: the containers run as `apps` (568), whose home is `/`, so Mesa can't write its shader cache without it. The cache lives in the container and is lost when it's recreated.
- **`group_add` 44 and 107** are the NAS's `video` and `render` groups, which own `/dev/dri/card0` and `renderD128`. Check them with `getent group video render` after a TrueNAS upgrade.
- **The embedding model is named after its preset section**: clients (paperless's `PAPERLESS_AI_LLM_EMBEDDING_MODEL`) send `harrier-oss-v1-0.6b`. Changing the model means re-embedding everything, as vectors from different models don't compare.
- **harrier expects an instruction on queries, not on documents**: `Instruct: <task>\nQuery: <question>`. Without one it retrieves about as well as Qwen3-Embedding-0.6B; with a generic one it scored 6–7 nDCG@10 points higher on Dutch BEIR-NL (FiQA, SciFact). paperless sends plain queries.
- **Image tags are `server-vulkan-bNNNN`**: a `.renovaterc.json5` rule parses the build number, so every llama.cpp build is a major update that Renovate never auto-merges.
