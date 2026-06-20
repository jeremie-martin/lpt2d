# lpt2d publish pipeline — end-to-end logic

A single-pass narrative of what the render → ship → YouTube pipeline
actually does. Read top-to-bottom; verify against your mental model.
Companion to `PUBLISH_DEPLOY.md` (which is the install/operator guide).

---

## 1. Producer side — when does a render run, what does it produce?

Three systemd **user** services, all routed to `scripts/lpt2d-render-and-ship.sh`.
They differ only in `LPT2D_WINDOW` env and the timer / `RuntimeMaxSec` bound.

| Service | Trigger | Window |
|---|---|---|
| `lpt2d-nightly.service` | timer `*-*-* 01:00:00`, `RuntimeMaxSec=6h` → ends 07:00 |
| `lpt2d-workday.service` | timer `Mon..Fri 09:30:00`, `RuntimeMaxSec=8h` → ends 17:30 weekdays |
| `lpt2d-manual.service`  | no timer; `schedule.sh start` / rofi; runs unbounded |

All three carry `Conflicts=` against the other two — only one runs at a
time. Both timers carry `Persistent=false`, so a missed firing (laptop
asleep at 01:00) is **not** caught up on next wake.

Stop semantics on every unit: `KillSignal=SIGTERM`, `TimeoutStopSec=120`,
`SuccessExitStatus=SIGTERM` (a clean SIGTERM exit is success), `Restart=no`.

Inside the shell entrypoint:

- **flock** against `$XDG_RUNTIME_DIR/lpt2d-render-and-ship.lock` —
  concurrent invocations exit 0 with a notice.
- **Env knobs**: `LPT2D_WINDOW` (default `manual`), `LPT2D_RESOLUTION`
  (`1080p`), `LPT2D_REMOTE` (`holo@rpi.local`), `LPT2D_REMOTE_INBOX`
  (`/home/holo/lpt2d-publish/inbox`).
- **OUT dir**: `renders/lpt2d_iris_${WINDOW}_${UTC_TS}_${RESOLUTION}` — one
  per service start.
- **Signals**: `trap on_signal INT TERM` sets `STOP=1` and forwards
  SIGTERM to the in-flight render. Under systemd this is mostly redundant
  — `KillMode` defaults to `control-group`, so the cgroup-wide SIGTERM
  hits everyone (bash + python + ffmpeg). The forward exists for
  direct-shell invocations.
- **EXIT trap**: `cleanup_partials; ship_session_bundles || true`. Always
  fires — clean exit, SIGTERM, or crash.

Main loop:

1. `cleanup_partials` — rmtree any `$OUT/<dir>` with `params.json` but no
   `verdict.json`.
2. `iris_demo.py --out $OUT -n 1 --resolution $RESOLUTION --no-index` in
   the background.
3. `wait $RENDER_PID`.
4. `ship_session_bundles`.

`iris_demo.py` pins `--branch solo_white`, `--duration 15.0`, and pulls
the rest from `RESOLUTION_PRESETS`. The `1080p` preset is
`1080x1920, rays=6_000_000, fps=60, depth=12, fast=False, crf=15`.

`iris_batch.main` runs `n=1` per call: builds an RNG seeded from
`(seed, i).__hash__()`, runs `_search_variant` (up to `--max-attempts=500`
of `iris.sample → iris.build → iris.check` until a `verdict.ok` passes),
then `_render_variant` writes (in order):

- `params.json` (before render)
- `frame.shot.json`
- `video.mp4`
- `verdict.json` — written **last**: this is the complete-bundle sentinel.

Curated sampling (`iris.py`):
- `LIGHT_REGIMES = ("loop", "patrol", "two_well", "chase")` — explicit
  production tuple, asserted as a subset of `iris_motion.REGIME_NAMES`.
- `_BRANCHES` weights: only `solo_white` non-zero, asserted at module load.
- `GEOM_KINDS` sampled freely from `{none, counter_rot, wedge_breathe, ring_pulse}`.

Quality gate (`iris.check`): probe at fps=4, depth=12, accept if ≥ 30%
of probe frames hit `(mean_luma 0.425..0.575, rms_contrast ≥ 0.25,
clipped ≤ 0.40, p05_luma ≤ 0.20)`.

## 2. Producer side — when and how does shipping happen?

Inline per bundle. **No background sweep, no scanning of the wider
`renders/` tree.** Only bundles produced by the current session ship.

`ship_bundle(b)`:

1. Verdict gate. If `verdict.json` exists with `ok=false`, `touch .shipped`
   locally and skip. The bundle stays on disk but is permanently flagged
   — never re-evaluated.
2. `rsync -a --partial --mkpath --timeout=60 --exclude=.shipped
   --exclude=video_published.mp4 $b/ $REMOTE:$INBOX/.staging_${name}.${PID}/`.
   Dot-prefixed staging dir is invisible to the watcher.
3. `ssh -o ConnectTimeout=30 $REMOTE` runs:
   `if [[ -e <final> ]]; then rm -rf <staging>; exit 1; else mv -- <staging> <final>; fi`.
   The "refuse if target exists" guard is **explicit** — POSIX
   `mv src dst/` would otherwise move src *into* dst when dst is a
   directory (silent merge would corrupt an already-shipped bundle).
4. On success: `touch $b/.shipped` (local marker; distinct from the
   remote's `uploaded`/`failed` markers).

`ship_session_bundles()` iterates `$OUT/*/`, filters to
`verdict.json && !.shipped`, calls `ship_bundle` per match (swallows
failures with `|| true`). Under normal operation this hits exactly one
bundle per call — the loop only exists to recover prior-iteration
shipping failures.

EXIT trap recovery: `cleanup_partials` first (rmtree any partial), then
`ship_session_bundles` (catch any complete-but-not-yet-shipped).

`rsync --timeout=60` and `ssh -o ConnectTimeout=30` are local per-call
limits. Combined with `TimeoutStopSec=120` on the unit, a hung remote
cannot stall service shutdown beyond ~120 s.

## 3. Consumer side — watcher host

The watcher currently runs on a Pi 5 (`holo@rpi.local`, Debian Bookworm,
Python 3.11.2, ffmpeg 5.1.6 native). Unit: `Type=simple`, `Restart=always`,
`RestartSec=30s`, default `KillMode=control-group`. PATH prepended with
`~/lpt2d-publish/bin` for hosts where the apt-shipped ffmpeg is too old
(< 5.0 misses `-display_rotation`); on the Pi this dir is empty and the
prepend is a no-op fallthrough to `/usr/bin`. ExecStart:

```
python -m publish watch \
    --inbox ~/lpt2d-publish/inbox \
    --music-dir ~/lpt2d-publish/music \
    --credentials-dir ~/lpt2d-publish/credentials \
    --state-file ~/lpt2d-publish/state.json \
    --ledger-dir ~/lpt2d-publish \
    --log-file ~/lpt2d-publish/watcher.log \
    --privacy public \
    --playlist PL2G6-wO4Mi9-_XhA9GiD6Pd8N3K2X0NQO \
    --min-interval 7200 \
    --interval 60
```

Watch loop:

```python
while True:
    for bundle in _pending_bundles(inbox):
        try: result = _handle(bundle, ...)
        except RateLimitError as e: time.sleep(e.retry_after or 3600); break
        except Exception: logger.exception(...); continue
        if result is HandleResult.THROTTLED: break
    time.sleep(60)
```

A `RateLimitError` aborts the whole tick after a sleep. A `THROTTLED`
result also breaks (no later fresh bundle can succeed in the same tick).
Generic exceptions log and skip.

`_pending_bundles`:

- Skip non-dirs.
- Skip dot-prefixed names (`.staging_*` from the producer).
- `uploaded` marker present → `resumed` queue, newest marker first.
- `failed` marker present → ignored entirely.
- Otherwise: must have `video.mp4 + params.json` and
  `mtime(video) ≥ now − 5 s` → `fresh` queue, newest video first.
- Return `resumed + fresh` so resumed bundles always drain before fresh;
  each queue is LIFO (a throttle-blocked fresh bundle must not starve
  cleanup, but fresh uploads still prefer the newest completed bundle).

`_handle`, in this exact order:

1. **Resume short-circuit**: `uploaded` marker exists → `_finalize_resumed` → return `RESUMED`.
2. **Throttle gate**: `state.seconds_until_next_allowed(min_interval) > 0` → return `THROTTLED`.
3. **JSON read fail-closed**: `_read_json_optional` for params + verdict;
   missing is OK, parse error → `_record_failure("…unreadable…")`.
4. **Verdict gate**: `verdict.ok==False` → `_record_failure("verdict.ok == false")`.
5. **Metadata**: `PublishOverrides.from_bundle` reads optional `publish.json`;
   `_resolve_metadata` picks `(title, description, tags)` from the random
   pool unless overridden.
6. **Post-process**: `post.process(bundle/video.mp4, music=True,
   music_dir, music_override)`:
   - ffprobe → if `width > height`, prepend `-display_rotation 90` to
     ffmpeg input options. **The production 1080x1920 path does not rotate**
     (already portrait). Rotation is for legacy 16:9 sources.
   - Random music or override pick; `ffmpeg -c:v copy -c:a aac` mux to
     `video_published.mp4`.
   - `FileNotFoundError` (typo'd music name) → `_record_failure("music
     override not found: '…'")`.
7. **Upload**: `RateLimitError` re-raised to outer loop. Other
   exceptions → `_record_failure("upload failed: …")`.
8. **Crash-safe finalize**, exact order:
   - `_build_upload_entry(...)` (ffprobes processed file for duration,
     stats for size).
   - `atomic_write_text(<bundle>/uploaded, json, fsync_dir=True)` —
     temp-write → fsync(file) → os.replace → fsync(dir). Once this
     returns, the marker is durable across crash.
   - `state.record_upload()` — atomic state.json (no dir-fsync; a torn
     rename here just looks like "no last_upload_at recorded yet").
   - `shutil.rmtree(bundle)`.
   - `ledger.append_upload(entry)` — append → flush → fsync.

## 4. OAuth / YouTube specifics

Credentials at `~/lpt2d-publish/credentials/`:
- `client_secrets.json` (Google Cloud Console → OAuth 2.0 desktop client).
- `token.pickle` (cached refresh + access tokens).

`YouTubeUploader.authenticate`:

1. Load `token.pickle`.
2. If creds invalid but a refresh token is present → `creds.refresh(Request())`.
3. If still invalid → `InstalledAppFlow.run_local_server(port=0)` (browser
   prompt). **Headless caveat**: on a remote host without a browser this would hang; bootstrap
   token.pickle locally first then `scp`.
4. Pickle creds back.
5. Build `googleapiclient.discovery.build("youtube", "v3", ...)`.

Per-upload (`upload`):
- `videos().insert(part="snippet,status", category_id="1"
  (Film & Animation), selfDeclaredMadeForKids=False, ...)`.
- `MediaFileUpload(resumable=True, chunksize=10 MiB)`.
- After success, if `playlist_id` set, `playlistItems().insert`.
  Playlist insert errors are logged but swallowed.
- HTTP error mapping:
  - 403 with `quotaExceeded | rateLimitExceeded | userRateLimitExceeded
    | dailyLimitExceeded` → `RateLimitError`.
  - 429 → `RateLimitError(retry_after)`.
  - else → `UploadError`.

## 5. End-to-end happy path (one bundle)

1. **01:00:00** systemd starts `lpt2d-nightly.service` →
   `lpt2d-render-and-ship.sh`. Lock acquired. EXIT trap armed.
2. **Iter 1**: `cleanup_partials` (no-op); `iris_demo.py -n 1`.
3. **Search** loop: up to 500 sample/build/check rounds; first
   `verdict.ok` wins.
4. `out_dir/params.json` written, then `frame.shot.json`, then
   `video.mp4` (15 s, 60 fps, 6M rays, depth 12, ffmpeg crf=15) — the
   multi-minute encode.
5. `verdict.json` written **last** — producer/consumer rendezvous point.
6. `wait $RENDER_PID` returns; `ship_session_bundles` →
   `ship_bundle`:
   - verdict ok → rsync to staging dir on the watcher host → ssh atomic mv → `touch .shipped`.
7. Loop iterates.

Meanwhile on the watcher host:

8. Watcher tick (every 60 s). `_pending_bundles` finds the bundle.
9. `_handle`: no marker; throttle slot open (or wait); params/verdict OK.
10. `post.process`: 1080x1920 → no rotation. Random music muxed.
11. `upload_fn` → resumable upload → `yt_id` → `_add_to_playlist`.
12. `_build_upload_entry`.
13. **marker (atomic + fsync_dir) → state → rmtree → ledger (fsync)**.
14. Next tick: throttled by `state` for ~3600 s.

## 6. Failure paths — what's left on disk

| Failure | Local state | Remote state |
|---|---|---|
| **SIGTERM during render** | EXIT trap rmtrees the partial; siblings keep `.shipped` | unchanged |
| **render exits non-zero** (GPU OOM) | `wait \|\| true` swallows; loop iterates again. Final EXIT cleanup catches debris | unchanged |
| **rsync fails** (network) | bundle has `verdict.json` no `.shipped`; retried next iteration | possibly an orphan `.staging_*.<pid>` (nothing prunes them; watcher skips) |
| **remote target already exists** | bundle stays unshipped; same retry loop | prior bundle intact; staging dir self-rm'd |
| **watcher killed mid-upload, before marker** | unaffected | bundle in inbox no marker; on restart goes to fresh queue → **re-uploaded (duplicate YT video)**. Millisecond window. |
| **watcher killed after marker, before rmtree** | unaffected | bundle has `uploaded`; on restart goes to resumed queue → `_finalize_resumed` → rmtree → `resumed=True` ledger line. **No re-upload.** |
| **YouTube quotaExceeded** | unaffected | watcher sleeps 3600 s, breaks tick. Bundle stays, retried later. |
| **publish.json:music missing** | unaffected | `FileNotFoundError` → `_record_failure("music override not found: …")` → failed.jsonl + rmtree |
| **verdict.json malformed** | unaffected | `JSONDecodeError` → `_record_failure("verdict.json unreadable: …")` → failed.jsonl + rmtree |

## 7. Storage / state surface

**Local (workstation):**

```
$ROOT/renders/lpt2d_iris_<window>_<UTC>_<resolution>/
   <bundle>/
     video.mp4
     params.json
     verdict.json     # last-written, sentinel
     frame.shot.json
     .shipped         # touched after successful rsync+rename
$XDG_RUNTIME_DIR/lpt2d-render-and-ship.lock
```

**Watcher host (currently `holo@rpi.local`):**

```
~/lpt2d-publish/
   inbox/<bundle>/
     video.mp4, params.json, verdict.json, frame.shot.json
     [publish.json]                # optional per-bundle overrides
     [uploaded | failed]            # lifecycle markers
   music/                           # random pool per upload
   credentials/
     client_secrets.json, token.pickle
   state.json                       # last_upload_at (rate limit)
   uploads.jsonl                    # append-only ledger
   failed.jsonl                     # append-only ledger
   watcher.log                      # rotating loguru, 30 days
   venv/                            # python venv (no C++)
   bin/ffmpeg, bin/ffprobe          # static ≥5.0
~/lpt2d/                            # repo clone (publish module + unit symlinks)
```

Both producer and consumer rely on systemd's default
`KillMode=control-group`: SIGTERM goes to *every* pid in the unit's
cgroup. For the producer this means bash + python + ffmpeg all receive
SIGTERM at timer expiry — no orphan ffmpeg. For the watcher, `Restart=always`
+ `RestartSec=30s` plus the durable `uploaded` marker makes mid-upload
death recoverable.

## Sanity-check observations

Items where the implementation has small contract asymmetries worth a
second look but that aren't bugs today:

1. **Asymmetric finalize ordering**: success path is `marker → state →
   rmtree → ledger`; failure path is `marker → ledger → rmtree`.
   Intentional but worth confirming.
2. **`failed`-marker bundles are invisible to `_pending_bundles`**: if a
   failed bundle's subsequent `rmtree` somehow fails (transient ENOSPC),
   it sits in inbox forever — no `_finalize_failed` analog exists.
3. **`_resolve_metadata` truthy-tests `overrides.tags`**: an explicit
   empty list in `publish.json` falls back to the random pool rather than
   uploading with no tags. Slightly inconsistent with `title_hint` /
   `description_hint`, which fall back only when missing.
4. **Orphan `.staging_<name>.<pid>` dirs accumulate on the watcher host** when
   rsync succeeds but the SSH atomic-rename step fails (network glitch
   between the two SSH phases). The watcher correctly skips them but
   never reaps them.
5. **1080p preset uses `fast=False, crf=15`** — the higher-quality
   non-preview settings, consistent with "production" intent.
