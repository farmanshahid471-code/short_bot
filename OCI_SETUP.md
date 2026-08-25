# Oracle Cloud (Chicago) — Shorts bot, click by click

You are already in **US Midwest (Chicago)**. That is a US IP. Stay in this region.

Do **not** create the tiny default AMD VM (`VM.Standard.E2.1.Micro`, 1 GB RAM). Render mode will crash. Use the **Always Free Ampere** shape: **4 OCPU / 24 GB**.

---

## Part A — Create the VM (from the screen you are on)

### A1. Open the create wizard

1. On the right, under **Build**, click **Create a VM instance**.
2. If that is missing: hamburger menu (☰ top left) → **Compute** → **Instances** → **Create instance**.

### A2. Name and compartment

1. **Name:** `shorts-bot`
2. **Create in compartment:** leave **root** (or your only compartment).
3. **Placement:** leave the default Availability Domain. If create fails later with *Out of host capacity*, come back and try the other AD.

### A3. Image = Ubuntu (not Oracle Linux)

1. Under **Image and shape**, click **Change image**.
2. OS: **Canonical Ubuntu**.
3. Version: **24.04** or **22.04** Minimal/Regular (either is fine).
4. Click **Select image**.

### A4. Shape = Ampere 4 OCPU / 24 GB

1. Click **Change shape**.
2. **Instance type:** Virtual machine.
3. **Shape series:** **Ampere**.
4. Shape: **VM.Standard.A1.Flex**.
5. Sliders:
   - **OCPU:** `4`
   - **Memory:** `24` GB
6. You should see an **Always Free-eligible** badge. Click **Select shape**.

If Ampere is greyed out or *Out of capacity*, try the other Availability Domain. Do **not** fall back to the 1 GB AMD micro.

### A5. Networking — must have a public IP

1. Leave **Create new virtual cloud network** (first time) or select the default VCN.
2. Subnet: **Public subnet**.
3. **Assign a public IPv4 address:** **Yes** (Automatically assign).
4. Do not turn on a reserved IPv6-only setup.

### A6. SSH key — save this or you cannot log in

1. **Add SSH keys** → **Generate a key pair for me**.
2. Click **Save private key**. The file is usually `ssh-key-....key`.
3. Also click **Save public key** if shown.
4. Put both in a folder you will not delete, e.g. `C:\Users\YOU\oracle-ssh\`.
5. Do **not** close the wizard before the private key is saved.

### A7. Boot volume

1. Boot volume size: **50 GB** (Always Free allows up to 200 GB total).
2. Leave encryption default.

### A8. Create

1. Scroll down → **Create**.
2. Wait until **State = Running** (1–3 minutes).
3. On the instance page, copy **Public IP address** (looks like `150.136.x.x`). Write it down.

If create fails with **Out of host capacity**, change Availability Domain and try again. Chicago Ampere fills up often.

---

## Part B — Open SSH on the Oracle firewall

Oracle blocks everything until you add a rule.

1. ☰ → **Networking** → **Virtual Cloud Networks**.
2. Click the VCN (often `vcn-...`).
3. **Security Lists** → **Default Security List**.
4. **Add Ingress Rules**.
5. Fill **one** rule:
   - Stateless: **No**
   - Source CIDR: `0.0.0.0/0`
   - IP protocol: **TCP**
   - Destination port: `22`
   - Description: `SSH`
6. **Add Ingress Rules**.

Do **not** open port 5100. The panel stays on localhost and you use an SSH tunnel.

---

## Part C — SSH in from Windows

1. Open **PowerShell** on your PC.
2. Go to the folder where the key was saved:

```powershell
cd $HOME\oracle-ssh
```

3. Lock the key (Windows SSH refuses a loose key):

```powershell
icacls ssh-key-*.key /inheritance:r
icacls ssh-key-*.key /grant:r "$($env:USERNAME):(R)"
```

4. Connect (`ubuntu` for Ubuntu images, **not** root):

```powershell
ssh -i .\ssh-key-XXXX.key ubuntu@PASTE_PUBLIC_IP
```

5. First time: type `yes` and Enter.
6. You should see a prompt like `ubuntu@shorts-bot:~$`.

If it times out: security list is missing, or the instance has no public IP.  
If `Permission denied`: wrong key or you used `root` instead of `ubuntu`.

---

## Part D — Install the bot on the VM

Paste these **on the VM** (the ubuntu@ prompt):

```bash
sudo apt-get update -y
sudo apt-get install -y git python3 python3-venv python3-pip ffmpeg fonts-dejavu-core fonts-liberation unzip
sudo timedatectl set-timezone America/Chicago

sudo mkdir -p /opt
sudo git clone -b arena/01a0325b-short-bot https://github.com/farmanshahid471-code/short_bot.git /opt/short_bot
sudo chown -R ubuntu:ubuntu /opt/short_bot

cd /opt/short_bot/yt_shorts_repost_bot
bash setup.sh
```

`setup.sh` takes a few minutes (Whisper/yt-dlp). When it finishes you should still be in `/opt/short_bot/yt_shorts_repost_bot`.

Oracle Ubuntu also has a local firewall. Leave it; we only need SSH from outside.

---

## Part E — Copy your working Windows files

On the **PC** (new PowerShell window, not the SSH session), from the folder that already works:

```powershell
$KEY = "$HOME\oracle-ssh\ssh-key-XXXX.key"
$IP  = "PASTE_PUBLIC_IP"
$SRC = "F:\new git\YOUR_WORKING_v7.1_FOLDER\yt_shorts_repost_bot"

scp -i $KEY "$SRC\accounts.json" ubuntu@${IP}:/opt/short_bot/yt_shorts_repost_bot/
scp -i $KEY "$SRC\cookies.txt"   ubuntu@${IP}:/opt/short_bot/yt_shorts_repost_bot/
scp -i $KEY "$SRC\.env"          ubuntu@${IP}:/opt/short_bot/yt_shorts_repost_bot/
scp -i $KEY "$SRC\bot_state.db"  ubuntu@${IP}:/opt/short_bot/yt_shorts_repost_bot/
scp -i $KEY -r "$SRC\accounts"   ubuntu@${IP}:/opt/short_bot/yt_shorts_repost_bot/
scp -i $KEY -r "$SRC\bgm"        ubuntu@${IP}:/opt/short_bot/yt_shorts_repost_bot/
```

Use the **v7.1** folder, not the old `short_bot-arena-01a03039-...` folder.

On the VM:

```bash
cd /opt/short_bot/yt_shorts_repost_bot
chmod 600 accounts.json cookies.txt .env 2>/dev/null || true
chmod 600 accounts/*/token.json accounts/*/client_secret.json 2>/dev/null || true
nano .env
```

If any line still has `F:\` or `C:\`, change it to a relative name (`cookies.txt`, `temp_clips`, `finished_shorts`).  
Keep:

```ini
WEBUI_HOST=127.0.0.1
WEBUI_PORT=5100
WEBUI_PASSWORD=
YT_COOKIES_FILE=cookies.txt
```

Save: `Ctrl+O`, Enter, `Ctrl+X`.

---

## Part F — Open the panel from your PC

**On the PC** (leave this window open):

```powershell
ssh -i $HOME\oracle-ssh\ssh-key-XXXX.key -L 5100:127.0.0.1:5100 ubuntu@PASTE_PUBLIC_IP
```

**On the VM** (same session is fine after you are logged in):

```bash
cd /opt/short_bot/yt_shorts_repost_bot
./run_bot.sh --mode webui
```

On the PC browser: http://127.0.0.1:5100

Check:

- Pink badge **v7.1 (Aug 24, 2026)**
- Tabs, green Connect dots, `@Simpson_Pimp` / `LIKE & SUBSCRIBE`
- Click **Run One Cycle Now** once and watch the log for  
  `Adding account watermarks with a PNG overlay`

Google login (**Connect / Test**) only works while this tunnel is open.

---

## Part G — Stay online after you close the laptop

On the VM (`Ctrl+C` the webui first):

```bash
sudo tee /etc/systemd/system/shorts-repost.service >/dev/null <<'EOF'
[Unit]
Description=YouTube Shorts repost bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/short_bot/yt_shorts_repost_bot
Environment=PYTHONPATH=/opt/short_bot
ExecStart=/opt/short_bot/yt_shorts_repost_bot/.venv/bin/python -m yt_shorts_repost_bot.main --mode scheduler
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now shorts-repost.service
sudo systemctl status shorts-repost.service
```

Logs:

```bash
journalctl -u shorts-repost.service -f
```

Confirm the VM is a US IP:

```bash
curl -s https://ipinfo.io
```

You should see `"country": "US"` and a Chicago-area city.

---

## YouTube Studio (do this on each channel)

Settings → Channel → Basic info:

- Country: **United States**
- Language: **English**

The Chicago IP does not replace that setting.

---

## Common problems

| What you see | Fix |
|---|---|
| Out of host capacity | Other Availability Domain, or wait and retry Ampere. Never use the 1 GB micro. |
| SSH timeout | Missing security-list port 22, or no public IP. |
| Permission denied (publickey) | Wrong key path, or user is not `ubuntu`. |
| Panel badge still v7.0 | You cloned `main` or copied the old Windows folder. Use branch `arena/01a0325b-short-bot`. |
| Connect YouTube does nothing | Tunnel is not running (`-L 5100:...`). |
| Token dies after ~7 days | Google Testing mode. Tunnel in and press Connect again. |
| Age-restricted fail | Re-export `cookies.txt` on the PC (current youtube.com site only) and `scp` it again. |
