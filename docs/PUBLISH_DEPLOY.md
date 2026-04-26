# Publish pipeline — server deployment

The publish pipeline runs on a VPS, watches an inbox for render bundles
shipped from the local machine, uploads them to YouTube one at a time,
records every upload in an append-only ledger, then deletes the bundle.

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

## One-time install (on the VPS)

```bash
ssh holo@vps

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
# scp client_secrets.json holo@vps:~/lpt2d-publish/credentials/

# 4. Bootstrap OAuth. This pops a browser the first time and writes
#    token.pickle. Run on a machine where you can complete the OAuth
#    redirect — for headless VPS, run it locally first then scp the
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
# 1. Install local systemd units + helpers.
~/prog/lpt2d/scripts/lpt2d-schedule.sh install
~/prog/lpt2d/scripts/lpt2d-schedule.sh enable

# 2. Wire env knobs (e.g. in ~/.config/environment.d/lpt2d.conf):
#    LPT2D_REMOTE=holo@vps
#    LPT2D_REMOTE_INBOX=/home/holo/lpt2d-publish/inbox
#    LPT2D_NIGHTLY_N=12

# 3. Confirm SSH key to the VPS works without a passphrase (rsync needs it).
ssh -o BatchMode=yes "$LPT2D_REMOTE" true && echo OK
```

## Verification

On the local machine, kick a one-shot:

```bash
~/prog/lpt2d/scripts/lpt2d-schedule.sh start
```

On the VPS, watch the lifecycle:

```bash
journalctl --user -u lpt2d-publish-watcher.service -f
ls ~/lpt2d-publish/inbox/        # should show bundles arriving
tail -f ~/lpt2d-publish/uploads.jsonl
```

After the first hour the second bundle's upload should appear; the inbox
shrinks as bundles get processed and deleted.

## Operational notes

- **Rate limit**: `--min-interval 3600` is hard-coded into the unit file. To
  change it (e.g. 30 min), edit
  `systemd/user/lpt2d-publish-watcher.service` in the repo, push, pull on
  the VPS, then `systemctl --user daemon-reload && systemctl --user
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
