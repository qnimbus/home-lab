# llama

Two [llama.cpp](https://github.com/ggml-org/llama.cpp) servers on the NAS's Radeon 890M (Vulkan), each with an OpenAI-compatible API behind Traefik:

| Service           | Address                      | Presets                                                                 |
| ----------------- | ---------------------------- | ----------------------------------------------------------------------- |
| `llama-server`    | `https://llama.vwn.app`      | `config/models.ini`: chat models, one loaded at a time                  |
| `llama-embedding` | `https://embeddings.vwn.app` | `config/models.embedding.ini`: Qwen3-Embedding-0.6B, last-token pooling |

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

- **They share the GPU and the system RAM** (the 890M has no memory of its own). Vulkan sees about 42 GB: a 30B/35B chat model (19–22 GB) and the embedding model fit together, two chat models barely; `--models-max 1` keeps it to one.
- **`XDG_CACHE_HOME: /tmp/.cache`**: the containers run as `apps` (568), whose home is `/`, so Mesa can't write its shader cache without it. The cache lives in the container and is lost when it's recreated.
- **`group_add` 44 and 107** are the NAS's `video` and `render` groups, which own `/dev/dri/card0` and `renderD128`. Check them with `getent group video render` after a TrueNAS upgrade.
- **Image tags are `server-vulkan-bNNNN`**: a `.renovaterc.json5` rule parses the build number, so every llama.cpp build is a major update that Renovate never auto-merges.
