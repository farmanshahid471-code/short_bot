# Run the Shorts bots on a Contabo US VPS

A US server IP does **not** make YouTube recommend you to Americans by itself.
YouTube uses the **channel country**, language, titles, and who actually watches.
The VPS is still useful: the bot stays online 24/7 and uploads from a US address.

## 1. Order the VPS

On Contabo, pick:

| Choice | Use this |
|---|---|
| Location | **United States** — Central (St. Louis) or East (New York). Do **not** pick Germany. |
| Image | **Ubuntu 24.04** (or 22.04) |
| Size | **Cloud VPS 10** (4 vCPU / 8 GB) if you use **render** mode. 4 GB is tight. |
| Extra | Enable **automatic backups** if offered |

Windows VPS also works (copy your current folder and run `run_ui.bat`), but Ubuntu is cheaper and what these scripts expect.

Set a long root password. After it is provisioned you get an IP like `66.x.x.x`.

## 2. What to change (and what not to)

### Change in YouTube Studio (this matters more than the IP)

On each channel: **Settings → Channel → Basic info**

- Country: **United States**
- Language: **English**

### Change in the bot panel (optional)

Your current watermarks, hashtags, render mode, and 24/7 window can stay.

If you want posts only during US waking hours:

- Automatic posting time zone: **Eastern Time** or **Central Time**
- Window example: `06:00` → `22:00`
- Save Account Settings

24/7 is fine if you already like that.

### Change on the VPS `.env` only if you expose the panel

Leave these as they are if you use the SSH tunnel below:

```ini
WEBUI_HOST=127.0.0.1
WEBUI_PORT=5100
WEBUI_PASSWORD=
```

Do **not**:

- switch the Google OAuth client from **Desktop app** to Web
- set `YT_COOKIES_FROM_BROWSER=chrome` (no Chrome profile on a headless VPS)
- bind `WEBUI_HOST=0.0.0.0` without a strong `WEBUI_PASSWORD`

## 3. Copy your working Windows setup

On the PC, zip only the private files (not `.venv`):

```
yt_shorts_repost_bot\accounts.json
yt_shorts_repost_bot\accounts\
yt_shorts_repost_bot\cookies.txt
yt_shorts_repost_bot\.env
yt_shorts_repost_bot\bot_state.db
yt_shorts_repost_bot\bgm\
```

`bot_state.db` is the “already posted” memory. Copy it or the VPS will try those Shorts again.

Keep `cookies.txt` from a logged-in **18+** YouTube account (current site only). Age-restricted downloads still need it.

## 4. Install on Ubuntu

From Windows PowerShell or Contabo VNC:

```bash
ssh root@YOUR_VPS_IP
```

```bash
apt-get update -y
apt-get install -y git python3 python3-venv python3-pip ffmpeg fonts-dejavu-core fonts-liberation unzip
timedatectl set-timezone America/New_York

cd /opt
git clone -b arena/01a0325b-short-bot https://github.com/farmanshahid471-code/short_bot.git
cd /opt/short_bot/yt_shorts_repost_bot
bash setup.sh
```

The pink badge must say **v7.1 (Aug 24, 2026)**. If it still says v7.0, you cloned the wrong branch.

Upload the zip from your PC (WinSCP, FileZilla, or `scp`), then:

```bash
cd /opt/short_bot/yt_shorts_repost_bot
# after unzipping into this folder:
chown -R root:root .
chmod 600 accounts.json cookies.txt .env 2>/dev/null || true
chmod 600 accounts/*/token.json accounts/*/client_secret.json 2>/dev/null || true
```

Edit `.env` if any path still looks like `F:\...`. Relative names (`cookies.txt`, `accounts/...`) are already correct.

## 5. Open the panel from your PC (do not put it on the public internet)

On your Windows PC, in PowerShell:

```powershell
ssh -L 5100:127.0.0.1:5100 root@YOUR_VPS_IP
```

Leave that window open. On the VPS:

```bash
cd /opt/short_bot/yt_shorts_repost_bot
./run_bot.sh --mode webui
```

On the PC open http://127.0.0.1:5100

You should see **v7.1**, your tabs, green Connect dots, and the same watermarks.

**Connect / Test YouTube** only works while that SSH tunnel is open, because Google sends the login back to `http://localhost`. If you copied `token.json` from the PC, you do not need to Connect again until Google expires it (about 7 days while the Cloud project is in Testing).

## 6. Keep it running after you close SSH

```bash
cat >/etc/systemd/system/shorts-repost.service <<'EOF'
[Unit]
Description=YouTube Shorts repost bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/short_bot/yt_shorts_repost_bot
Environment=PYTHONPATH=/opt/short_bot
ExecStart=/opt/short_bot/yt_shorts_repost_bot/.venv/bin/python -m yt_shorts_repost_bot.main --mode scheduler
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now shorts-repost.service
systemctl status shorts-repost.service
```

Logs:

```bash
journalctl -u shorts-repost.service -f
# or
tail -f /opt/short_bot/yt_shorts_repost_bot/shorts_repost.log
```

A good render still logs:

`Adding account watermarks with a PNG overlay`

To use the web panel later, stop fighting the service for port 5100: keep the scheduler as the 24/7 poster, and only start `--mode webui` when you need to change settings (stop the service first, or use the panel only through the tunnel when the service is stopped).

If you want **both** the scheduler and the panel at once, leave the service on `scheduler` and start the panel in a second SSH session. They share `accounts.json`; only one of them should be posting.

## 7. Firewall

```bash
ufw allow OpenSSH
ufw enable
```

Do **not** `ufw allow 5100` unless you also set a strong `WEBUI_PASSWORD` and understand the panel will be on the public internet.

## 8. After it is live

1. Click **Run One Cycle Now** once (via the tunneled panel) and watch the log.
2. Confirm the new Short has `@Simpson_Pimp` and `LIKE & SUBSCRIBE`.
3. Confirm the upload IP is US: https://ipinfo.io on the VPS (`curl https://ipinfo.io`).
4. Re-export `cookies.txt` on your PC if age-restricted downloads start failing.
5. If a tab stops uploading after a week, SSH-tunnel and press **Connect / Test YouTube** again.

## Clip bot

Same steps in `/opt/short_bot` with `./run_bot.sh --mode webui` (port **5000**) and a second systemd unit if you use that bot too. Tunnel:

```powershell
ssh -L 5000:127.0.0.1:5000 -L 5100:127.0.0.1:5100 root@YOUR_VPS_IP
```
