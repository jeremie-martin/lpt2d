# Publish pipeline — watcher-host deployment

The publish pipeline runs on a remote host (currently a Pi 5 at
`holo@rpi.local`; previously was a VPS — same setup steps work), watches
an inbox for render bundles shipped from the local machine, uploads them
to YouTube one at a time, records every upload in an append-only ledger,
then deletes the bundle.

## Layout

```
~/lpt2d-publish/
  inbox/          # rsync target — render bundles land here
  music/          # background tracks pool (random pick per upload)
  credentials/    # client_secrets.json + token.pickle
  uploads.jsonl   # append-only ledger of successful uploads
  failed.jsonl    # append-only ledger of terminal failures
  state.json      # last_upload_at (drives --min-interval)
  watcher.log     # rotating Loguru log
  venv/           # Python venv (no C++ build needed on the server)
~/lpt2d/          # this repo, cloned for the publish module + systemd unit
```

## One-time install (on the watcher host)

```bash
ssh holo@rpi.local

# 1. Clone the repo (publish/ is the only thing we need; no C++ build).
git clone <lpt2d repo url> ~/lpt2d
cd ~/lpt2d

# 2. Create publish layout + venv.
mkdir -p ~/lpt2d-publish/{inbox,music,credentials}
python3 -m venv ~/lpt2d-publish/venv
~/lpt2d-publish/venv/bin/pip install --upgrade pip
~/lpt2d-publish/venv/bin/pip install \
    loguru \
    google-auth-oauthlib \
    google-api-python-client

# 3. Drop the OAuth client into credentials/. Get this from Google Cloud
#    Console → APIs & Services → Credentials → OAuth 2.0 Client → Desktop.
# scp client_secrets.json holo@rpi.local:~/lpt2d-publish/credentials/

# 4. Bootstrap OAuth. This pops a browser the first time and writes
#    token.pickle. Run on a machine where you can complete the OAuth
#    redirect — for a headless watcher host, run it locally first then scp the
#    token.pickle, OR use ssh -L to tunnel the redirect.
~/lpt2d-publish/venv/bin/python -m publish upload --help

# 5. Drop one or more music tracks into ~/lpt2d-publish/music/
#    (m4a, aac, mp3, opus, ogg, wav, or flac).

# 6. Install the systemd user unit (from the cloned repo).
mkdir -p ~/.config/systemd/user
ln -sf ~/lpt2d/systemd/user/lpt2d-publish-watcher.service \
       ~/.config/systemd/user/lpt2d-publish-watcher.service

# Enable lingering so the user-mode service runs without a login session.
sudo loginctl enable-linger "$USER"

systemctl --user daemon-reload
systemctl --user enable --now lpt2d-publish-watcher.service
systemctl --user status lpt2d-publish-watcher.service
```

## Local-side setup (dev workstation)

```bash
# 1. Install all five systemd unit symlinks + reload daemon.
~/prog/lpt2d/scripts/lpt2d-schedule.sh install

# 2. Enable both timers (nightly 01:00, workday Mon–Fri 09:30).
~/prog/lpt2d/scripts/lpt2d-schedule.sh enable

# 3. Wire env knobs (e.g. in ~/.config/environment.d/lpt2d.conf):
#    LPT2D_REMOTE=holo@rpi.local
#    LPT2D_REMOTE_INBOX=/home/holo/lpt2d-publish/inbox
#    LPT2D_RESOLUTION=1080p  # iris_demo preset

# 4. Confirm SSH key to the watcher host works without a passphrase (rsync needs it).
ssh -o BatchMode=yes "$LPT2D_REMOTE" true && echo OK
```

## Schedule

Three systemd user services all invoke `scripts/lpt2d-render-and-ship.sh`,
differing only in the env var that names the run and the `RuntimeMaxSec`
that bounds it:

| Service | Trigger | Window | Stops at |
|---|---|---|---|
| `lpt2d-nightly.service` | timer `*-*-* 01:00:00` | every night, 6 hours | 07:00 daily |
| `lpt2d-workday.service` | timer `Mon..Fri 09:30:00` | weekday, 8 hours | 17:30 weekdays |
| `lpt2d-manual.service` | rofi / `schedule.sh start` | unbounded | manual `pause`/`stop` |

All three `Conflicts=` each other, so only one runs at a time.

The script renders one bundle at a time in a loop (`iris_demo.py -n 1`)
and ships **that bundle and only that bundle** to the watcher host the moment it
completes, then loops. There is no background sweep and no scanning of
the wider `renders/` tree — old experimental directories are invisible
to the publish path.

When the timer expires (or the operator stops the service), the script
forwards SIGTERM to the in-flight render, then `rmtree`s the partial
bundle (the one with `params.json` but no `verdict.json`) on exit. Net
effect: never any half-rendered bundles on disk.

`Persistent=false` on both timers — a missed nightly does NOT fire on
next wake. If the laptop was asleep at 01:00, just hit "Start now (manual)"
in the rofi menu.

## Verification

On the local machine, kick a manual run:

```bash
~/prog/lpt2d/scripts/lpt2d-schedule.sh start
```

You can stop it any time via:

```bash
~/prog/lpt2d/scripts/lpt2d-schedule.sh pause     # leaves timers enabled
~/prog/lpt2d/scripts/lpt2d-schedule.sh stop      # also disables timers
```

On the watcher host, watch the lifecycle:

```bash
journalctl --user -u lpt2d-publish-watcher.service -f
ls ~/lpt2d-publish/inbox/        # bundles arrive ~30s after each render
tail -f ~/lpt2d-publish/uploads.jsonl
```

The first bundle uploads immediately after rsync; subsequent ones drip out
at `--min-interval` (3600s) cadence. The inbox shrinks as the watcher
processes and deletes each one.

## Operational notes

- **Rate limit**: `--min-interval 3600` is hard-coded into the unit file. To
  change it (e.g. 30 min), edit
  `systemd/user/lpt2d-publish-watcher.service` in the repo, push, pull on
  the watcher host, then `systemctl --user daemon-reload && systemctl --user
  restart lpt2d-publish-watcher.service`.
- **Privacy**: defaults to `private` to avoid surprises. Change with
  `--privacy unlisted` or `--privacy public` in the unit's `ExecStart`.
- **Failed bundles**: deleted on the server too (per design). The `reason`
  is recorded in `failed.jsonl` along with the full params/verdict so you
  can reproduce locally — no need to keep the bytes around.
- **Resume after crash**: the watcher writes an `uploaded` marker inside
  the bundle right after YouTube returns the id. If the watcher crashes
  before the ledger line + rmtree completes, the next tick sees the
  marker, finishes the bookkeeping, and deletes the bundle — no second
  upload.
- **Credential rotation**: replace `client_secrets.json` in
  `~/lpt2d-publish/credentials/`, delete `token.pickle`, then run
  `python -m publish upload --help` once to re-prime OAuth.

## Local analysis

Both ledgers are JSONL — analyze with `jq` or pandas:

```bash
# All uploads with iris_diagonal layout, sorted by wall_albedo:
jq -c 'select(.params.iris_composition=="iris_diagonal")
       | {url:.youtube_url, title, wall_albedo:.params.wall_albedo}' \
   ~/lpt2d-publish/uploads.jsonl | sort -t: -k4 -n
```

```python
import pandas as pd
uploads = pd.read_json("~/lpt2d-publish/uploads.jsonl", lines=True)
params = pd.json_normalize(uploads["params"])
df = pd.concat([uploads.drop(columns=["params", "verdict"]), params], axis=1)
df.groupby("iris_composition")["youtube_id"].count()
```
