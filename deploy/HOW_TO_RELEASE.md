# How to release SmartWagers

Use this when shipping a version to a Windows venue. Build the package once. A **new site** is installed from that package. An **existing site** receives the same package over Tailscale, or from USB when the site is offline.

Do not copy an uncommitted working tree to a server. Do not overwrite `.env`, `.email_password`, PostgreSQL data, or `C:\SmartWagers\data\master_lock.state`.

This guide uses these machine names:

- **Developer/operator PC** — your Windows 11 development PC. It holds the Git
  checkout, release packages, private SSH keys, and `deploy\sites.json`. Run
  build, `fleet.py`, `tailscale ping`, and outbound `ssh` commands here.
- **Target server PC** — the Windows PC installed at the venue. It runs
  SmartWagers, PostgreSQL, Memurai, Tailscale, and Windows OpenSSH Server. Run
  server installation, service, firewall, and `.env` commands here.
- **Teller PC** — a cashier workstation on the venue LAN.
- **Tailscale admin console** — a website that may be opened from either PC,
  although the developer/operator PC is recommended.

Never copy the SSH private key to the target server. Only its `.pub` public key
is copied there.

Related pages:

- First-time Windows clicks and dialogs: [README.md](README.md)
- Day-of-event checks at the venue: [OPERATOR_RUNBOOK.md](OPERATOR_RUNBOOK.md)
- Failed apply or restore: [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md)

## 1. Build the release

**Run on: Developer/operator PC**, in the repository root, from a clean checkout
of the tag or commit to ship:

```bash
git checkout v1.14.0
python deploy/pre_release.py
python deploy/build_release.py --ref v1.14.0 --output releases --field-kit
```

`pre_release.py` runs the test suite, `manage.py check`, and `makemigrations --check`. Stop if any of those fail. `build_release.py` runs those checks again unless you pass `--skip-checks`.

The command writes two folders under `releases/`:

| Folder | Use |
| --- | --- |
| `SmartWagers-<timestamp>-<sha>/` | The package. Fleet upload and `APPLY_RELEASE.bat` both use this. |
| `SmartWagers-<timestamp>-<sha>-field-kit/` | USB copy for a site with no VPN. Contains `release/`, `tools/`, and `CHECKLIST.txt`. |

To keep the previous package on the USB drive for onsite rollback:

**Run on: Developer/operator PC**, in the repository root:

```bash
python deploy/build_release.py --ref v1.14.0 --output releases --field-kit --previous-package releases/<previous-package> --skip-checks
```

Record the commit from `release.json` (`commit_sha`). You will pass that value to `fleet.py verify`.

The package contains the Git tree, SHA-256 checksums, Python 3.12, the database schema level, and Windows wheels. It does not contain venue secrets.

## 2. New deployment

Do this once per venue. Later updates follow section 3.

### 2.1 Prepare the target server

**Do on: Target server PC.**

1. Install **Python 3.12** for all users and add it to PATH. Do not use Python 3.14.
2. Install **Memurai** and confirm `memurai-cli ping` returns `PONG`.
3. Install **PostgreSQL** with command-line tools. Leave it listening on localhost only, and put its `bin` directory on PATH.
4. Extract **NSSM** to `C:\SmartWagers\nssm\nssm.exe`.
5. Install **Tailscale** and **Windows OpenSSH Server**, then finish the firewall, SSH key, and hostname steps in [section 2.6](#26-tailscale-and-openssh). Do not publish ports 22, 5432, 6379, or 8080 to the public internet.

Copy the package **payload** from the developer/operator PC or field-kit USB to
the target server PC:

```text
releases/SmartWagers-.../payload/  ->  C:\SmartWagers\GameFowl\
```

Also copy these installer files from the package root into `C:\SmartWagers\GameFowl\deploy\` if they are not already in the payload: `apply_usb_release.py`, `apply_engine.py`, and `release_metadata.py`.

### 2.2 Create the site configuration

**Do all steps in this subsection on: Target server PC.**

1. Edit `SERVER_IP` in `deploy\1_setup_env.bat` to this server's LAN address.
2. Run `deploy\1_setup_env.bat` as Administrator. It writes `C:\SmartWagers\GameFowl\.env`.
3. Create the database with the generated `.env` values:

**Run on: Target server PC**, in Command Prompt:

```cmd
psql -U postgres -d postgres
CREATE ROLE smartwagers_app WITH LOGIN PASSWORD '<POSTGRES_PASSWORD from .env>';
CREATE DATABASE smartwagers OWNER smartwagers_app ENCODING 'UTF8';
\q
```

4. Add the venue name, then add this server's Tailscale names to the host lists as in [section 2.6](#26-tailscale-and-openssh):

```text
LOCATION=Venue Name
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,<LAN-IP>,<tailscale-ipv4>,<magicdns-name>
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://<LAN-IP>:8080,http://<tailscale-ipv4>:8080,http://<magicdns-name>:8080
```

Leave `SMARTWAGERS_SERVER_URL` on the LAN address. Teller PCs use that URL and stay off the tailnet.

5. Put the SMTP password in `.email_password` next to `manage.py`, or set `EMAIL_HOST_PASSWORD` in `.env`.
6. Run `python manage.py hash_master_lock_key` and paste the result into `MASTER_LOCK_PASSWORD_HASH`.
7. Run `deploy\6_init_master_lock.bat`. Restrict `C:\SmartWagers\data` to Administrators and the Daphne service account.
8. Run `python manage.py check_site_config`. It prints missing setting names, not secret values.

### 2.3 Install and start

**Run on: Target server PC**, as Administrator, in order:

1. `deploy\2_install_deps.bat`
2. `deploy\3_init_database.bat`
3. `python manage.py createsuperuser`
4. In Django admin (`http://localhost:8080/admin/` after the service is up), create groups `admin`, `teller`, and `display`, then assign users.
5. `deploy\4_install_service.bat` — registers **SmartWagers-Daphne** and schedules the daily backup plus commission-email retry.
6. `deploy\5_firewall.bat` — opens TCP 8080 on the LAN.

### 2.4 Tellers and remote access

1. On the **target server PC**, run `local_print_agent\prepare_vendor.bat` once while the server has internet.
2. On each cashier PC, install the receipt printer, download the print agent from **Admin → Print Agent**, and run `install_print_agent.bat`.
3. Set `SMARTWAGERS_SERVER_URL=http://<LAN-IP>:8080` in the teller `server.env`.
4. On the **developer/operator PC**, register this venue in `deploy/sites.json` as in [section 2.6](#26-tailscale-and-openssh). Set `"group": "canary"` for the first site you will update remotely.

### 2.5 Confirm the new site

Check each item on the machine named:

- **Teller PC:** Open `http://<LAN-IP>:8080/login`, place a test bet, and print
  a receipt.
- **Target server PC:** Open
  `http://localhost:8080/health/ready/`; it must return `"ok": true`.
- **Target server PC:** Confirm an admin can open a fight and the display board
  updates.
- **Target server PC:** Confirm
  `C:\SmartWagers\backups\last_backup.json` appears after the first scheduled
  backup. If needed, run `python deploy\postgres_tools.py backup-maintain` from
  `C:\SmartWagers\GameFowl`.
- **Target server PC:** Reboot it and confirm PostgreSQL, Memurai,
  SmartWagers-Daphne, Tailscale, and `sshd` start without manual action.
- **Developer/operator PC:** Run `tailscale status` and repeat the SSH test from
  section 2.6 after the target server reboots.

Register the installed commit so the next remote update can see what is running. If you applied the package with `APPLY_RELEASE.bat` after the install scripts, this file already exists. Otherwise the first remote deploy in section 3 writes it.

### 2.6 Tailscale and OpenSSH

Complete this section once for every server that will receive remote updates.
Tailscale provides the private network path, while Windows OpenSSH provides the
`ssh` and `scp` services used by `fleet.py`. Do not enable Tailscale SSH for this
workflow: `fleet.py` connects to Windows OpenSSH on TCP 22.

The intended network layout is:

- Teller PCs use `http://<LAN-IP>:8080` and do not join the tailnet.
- Approved release managers reach TCP 22 and 8080 through Tailscale.
- Venue servers cannot initiate connections to other venue servers.
- PostgreSQL and Memurai remain bound to `127.0.0.1`.
- The venue router has no port forwards for 22, 5432, 6379, or 8080.
- The server is not an exit node or subnet router. Do not enable Funnel, Serve,
  advertised routes, or an exit node.

Replace values in angle brackets below. Use a short venue identifier such as
`smartwagers-cebu` for `<server-name>` and the release manager's real Tailscale
login for `<operator-email>`.

#### A. Configure the tailnet

**Do in: [Tailscale admin console](https://login.tailscale.com/admin)**, normally
using a browser on the developer/operator PC. These are website settings, not
PowerShell commands.

1. Open **DNS** and enable **MagicDNS**.
2. Open **Access controls**. Merge the following entries into the existing
   policy; do not replace unrelated groups, grants, or tests. Replace the sample
   email. Add every authorized release manager to the group.

```json
{
  "groups": {
    "group:smartwagers-operators": [
      "<operator-email>"
    ]
  },
  "tagOwners": {
    "tag:smartwagers-server": [
      "group:smartwagers-operators"
    ]
  },
  "grants": [
    {
      "src": ["group:smartwagers-operators"],
      "dst": ["tag:smartwagers-server"],
      "ip": ["tcp:22", "tcp:8080"]
    }
  ]
}
```

Tailscale access is deny-by-default once the broad default grant is removed.
If the policy still contains a grant from `*` to `*`, this narrow rule does not
restrict anything; remove or narrow that broad grant only after confirming that
other tailnet users will not lose access they need.

Tag only the venue servers. Do not tag a release manager's laptop: keeping it
user-owned lets the `group:smartwagers-operators` source rule identify the
signed-in person.

#### B. Join and name the Windows server

**Do all steps in this subsection on: Target server PC**, except the explicitly
named Tailscale admin-console actions.

1. Install the current Windows Tailscale client from
   [tailscale.com/download/windows](https://tailscale.com/download/windows).
2. Sign in from the Tailscale tray icon with an account allowed into this
   tailnet. If device approval is enabled, approve the new machine on the
   **Machines** page.
3. On the **target server PC**, open PowerShell as Administrator and assign a
   stable, unique machine name:

**Run on: Target server PC — PowerShell as Administrator.**

```powershell
tailscale set --hostname=<server-name>
tailscale ip -4
tailscale status
```

4. In **Admin console → Machines**, open the server's menu:
   - Choose **Edit machine name**, confirm `<server-name>`, and turn off
     **Auto-generate from OS hostname**.
   - Choose **Edit tags** and add `tag:smartwagers-server`.
   - Choose **Disable key expiry**. Venue servers are unattended; otherwise the
     default node-key expiry can take remote deployment offline.
5. Record both values:
   - Tailscale IPv4: the `100.x.y.z` printed by `tailscale ip -4`
   - Full MagicDNS name: `<server-name>.<tailnet-name>.ts.net`, shown on the
     machine details page

Do not reuse a deleted machine entry. If Windows is rebuilt, remove the old
machine from Tailscale, enroll the replacement, reapply its tag, and accept its
new SSH host key on the developer/operator PC.

#### C. Install and secure Windows OpenSSH

The SSH account must be a local Windows administrator because a release stops
and starts services and writes under `C:\SmartWagers`. You may use
`Administrator`; a dedicated account such as `SmartWagersDeploy` is preferred.
Create and record the account before disabling SSH password authentication.

1. Install OpenSSH Server and make it persistent.

**Run on: Target server PC — PowerShell as Administrator.**

```powershell
$capability = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
if ($capability.State -ne "Installed") {
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
}
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic
Get-Service sshd
Get-NetTCPConnection -State Listen -LocalPort 22
```

The final two commands must show `Running` and a listener on port 22.

2. Verify that Microsoft's OpenSSH Client is installed.

**Run on: Developer/operator PC — PowerShell as Administrator.**

```powershell
$client = Get-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
if ($client.State -ne "Installed") {
    Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
}
Get-Command "$env:WINDIR\System32\OpenSSH\ssh-keygen.exe"
```

Windows OpenSSH `ssh-keygen.exe` supports `-t`. If `ssh-keygen -t ...` reports
that `-t` is unknown, PowerShell is resolving a different program. The commands
below use the full executable path to avoid aliases and PATH conflicts.

Close the Administrator window.

**Run on: Developer/operator PC — normal PowerShell under the operator's
Windows account.** Generate one Ed25519 key for this venue:

```powershell
$venue = "<venue>"
$keyDirectory = Join-Path $env:USERPROFILE ".ssh"
$keyPath = Join-Path $keyDirectory "smartwagers_$venue"
New-Item -ItemType Directory -Path $keyDirectory -Force | Out-Null
& "$env:WINDIR\System32\OpenSSH\ssh-keygen.exe" `
    -t ed25519 `
    -f $keyPath `
    -C "SmartWagers $venue"
Get-Content "$keyPath.pub"
```

Replace `<venue>` with a short name such as `cebu`; do not include the angle
brackets. Enter a passphrase when prompted. Enable Windows `ssh-agent` once
as follows.

**Run on: Developer/operator PC — PowerShell as Administrator.**

```powershell
Set-Service -Name ssh-agent -StartupType Automatic
Start-Service ssh-agent
```

Before each release, load the private key.

**Run on: Developer/operator PC — normal PowerShell under the same Windows
account that generated the key.**

```powershell
$venue = "cebu" # Use the same name used when the key was generated.
$keyPath = Join-Path $env:USERPROFILE ".ssh\smartwagers_$venue"

Get-Service ssh-agent
Test-Path $keyPath
& "$env:WINDIR\System32\OpenSSH\ssh-add.exe" $keyPath
& "$env:WINDIR\System32\OpenSSH\ssh-add.exe" -l
```

`Get-Service` must show `Running`, `Test-Path` must print `True`, and the first
`ssh-add` command must print `Identity added`. Enter the private-key passphrase
when prompted. The final command then prints the Ed25519 fingerprint.

`The agent has no identities` from `ssh-add -l` only means that no key is loaded
for the current Windows user. If it appears after the add command:

1. Confirm `$keyPath` points to the private key, not the `.pub` file.
2. Run `Get-ChildItem "$env:USERPROFILE\.ssh"` and use the filename actually
   created in the earlier step.
3. Run these commands in a normal PowerShell window logged in as the operator,
   not in a PowerShell window running as another administrator account.
4. Read the output of the first `ssh-add` command; a bad path, incorrect
   passphrase, or unreadable key is reported there.

Keys loaded into `ssh-agent` do not survive every sign-out or service restart,
so loading the key is a normal pre-release step. If unattended operation is
required, a key without a passphrase must be readable only by the operator's
Windows account. Never copy the private key to the venue server or commit it to
Git.

3. Copy the single `ssh-ed25519 ...` public-key line from the
   developer/operator PC. On the target server PC, put it in
   `C:\ProgramData\ssh\administrators_authorized_keys`. This special file is
   required for every account in the local Administrators group; that account's
   profile-level `.ssh\authorized_keys` is ignored.

**Run on: Target server PC — PowerShell as Administrator.**

```powershell
$keyFile = "C:\ProgramData\ssh\administrators_authorized_keys"
New-Item -ItemType File -Path $keyFile -Force | Out-Null
Add-Content -Path $keyFile -Value '<paste-public-key-here>'
icacls.exe $keyFile /inheritance:r /grant "*S-1-5-32-544:F" /grant "SYSTEM:F"
Restart-Service sshd
```

Add each public key only once, one key per line. The SID
`S-1-5-32-544` is the built-in Administrators group and works on localized
Windows installations. OpenSSH rejects this file if other users can modify it.

4. Test the key before disabling passwords. Use the `$keyPath` created above.

**Run on: Developer/operator PC — normal PowerShell.** This command connects
outbound to the target server:

```powershell
$sshUser = "SmartWagersDeploy"
$server = "<magicdns-name>"
& "$env:WINDIR\System32\OpenSSH\ssh.exe" `
    -i $keyPath `
    -o StrictHostKeyChecking=accept-new `
    "$sshUser@$server" `
    "whoami"
```

Replace `<magicdns-name>` with the target server's complete MagicDNS name.
The command must print the server account without asking for its Windows
password. A prompt for the SSH key's passphrase is normal unless it is loaded
in `ssh-agent`.

5. On the **target server PC**, open
   `C:\ProgramData\ssh\sshd_config` as Administrator. Set the following value,
   or uncomment and change the existing value:

```text
PasswordAuthentication no
```

Do not remove the existing `Match Group administrators` /
`AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys` block.
Validate the file before restarting:

**Run on: Target server PC — PowerShell as Administrator.**

```powershell
& "$env:WINDIR\System32\OpenSSH\sshd.exe" -t
if ($LASTEXITCODE -eq 0) { Restart-Service sshd }
```

Run the SSH test again with `-o BatchMode=yes`. It must still succeed without a
password prompt, because `fleet.py` always uses batch mode. Run that test from
the **developer/operator PC**, not the target server.

#### D. Restrict Windows Firewall to LAN and Tailscale

**Run all commands in this subsection on: Target server PC — PowerShell as
Administrator.**

Run `Get-NetAdapter` and record the exact LAN and Tailscale adapter names.
Common values are `Ethernet`, `Wi-Fi`, and `Tailscale`. Replace the two values
below if yours differ.

`deploy\5_firewall.bat` initially creates a broad TCP 8080 rule. Replace it, and
the broad rule created by OpenSSH installation, with interface-specific rules:

```powershell
$LanAlias = "Ethernet"
$TailAlias = "Tailscale"

Remove-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "OpenSSH from Tailscale" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "OpenSSH from Tailscale" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 22 -InterfaceAlias $TailAlias

Remove-NetFirewallRule -DisplayName "SmartWagers-Daphne" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "SmartWagers from LAN" -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "SmartWagers from Tailscale" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "SmartWagers from LAN" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 8080 -InterfaceAlias $LanAlias
New-NetFirewallRule -DisplayName "SmartWagers from Tailscale" -Direction Inbound `
    -Action Allow -Protocol TCP -LocalPort 8080 -InterfaceAlias $TailAlias
```

If the server uses Wi-Fi, set `$LanAlias = "Wi-Fi"`. If it legitimately serves
both Ethernet and Wi-Fi, create one LAN rule for each adapter. Do not create
inbound rules for 5432 or 6379.

Verify the resulting rules:

**Run on: Target server PC — PowerShell as Administrator.**

```powershell
Get-NetFirewallRule -DisplayName "OpenSSH from Tailscale","SmartWagers from LAN","SmartWagers from Tailscale" |
    Format-Table DisplayName,Enabled,Direction,Action
```

#### E. Configure Django and the developer/operator PC

This subsection connects the Django configuration on the target server with
the `fleet.py` configuration on the developer/operator PC. The instructions
below assume that `fleet.py` will be run from **Windows PowerShell**. Do not mix
Windows and WSL key paths.

For the examples below, assume:

- Venue name: `cebu`
- Target server machine name: `smartwagers-cebu`
- Full MagicDNS name: `smartwagers-cebu.tail287ec9.ts.net`
- Target server SSH account: `Administrator`
- Developer Windows account: `David`
- Private key:
  `C:\Users\David\.ssh\smartwagers_cebu`

Replace all example values with the values from your two PCs.

##### E1. Record the target server addresses

**Run on: Target server PC — PowerShell.**

```powershell
ipconfig
tailscale ip -4
$ts = tailscale status --json | ConvertFrom-Json
$ts.Self.DNSName.TrimEnd(".")
```

Record these three values:

1. **LAN IPv4** — from the active Ethernet or Wi-Fi adapter in `ipconfig`, for
   example `192.168.1.10`.
2. **Tailscale IPv4** — from `tailscale ip -4`, for example `100.80.20.10`.
3. **Full MagicDNS name** — from the last command, for example
   `smartwagers-cebu.tail287ec9.ts.net`.

The full MagicDNS name must start with the target server's machine name.
`tail287ec9.ts.net` by itself is only the tailnet domain and will not resolve as
a server.

##### E2. Update Django on the target server

**Run on: Target server PC — text editor as Administrator.**

Open:

```text
C:\SmartWagers\GameFowl\.env
```

Find and replace the three settings below. Use the exact values recorded in E1.
For the example addresses above, the result would be:

```text
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.10,100.80.20.10,smartwagers-cebu.tail287ec9.ts.net
DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://192.168.1.10:8080,http://100.80.20.10:8080,http://smartwagers-cebu.tail287ec9.ts.net:8080
SMARTWAGERS_SERVER_URL=http://192.168.1.10:8080
```

Important:

- Keep each setting on one line.
- Separate hosts and origins with commas but no spaces.
- Do not add a path or trailing slash to an origin.
- `SMARTWAGERS_SERVER_URL` stays on the LAN address because tellers use the
  venue LAN.

Save `.env`, then restart Django.

**Run on: Target server PC — PowerShell as Administrator.**

```powershell
Restart-Service "SmartWagers-Daphne"
Get-Service "SmartWagers-Daphne"
```

The service status must be `Running`. On the target server, open
`http://localhost:8080/health/ready/` and confirm `"ok": true` before
continuing.

##### E3. Prepare the developer/operator PC

**Run on: Developer/operator PC.**

1. Install Tailscale, sign in as an address listed in
   `group:smartwagers-operators`, and confirm that Tailscale is connected.
2. Open a **normal PowerShell window**, not PowerShell running as a different
   administrator account.
3. Change to the repository root—the folder containing `manage.py` and
   `deploy`.
4. Define the values for this venue. PowerShell variables do not carry into a
   new window, so run this again in every new PowerShell session:

```powershell
$venue = "cebu"
$server = "smartwagers-cebu.tail287ec9.ts.net"
$sshUser = "Administrator"
$keyPath = Join-Path $env:USERPROFILE ".ssh\smartwagers_$venue"
```

`$sshUser` is a local Windows administrator account that exists on the target
server. If you created `SmartWagersDeploy`, use that instead of
`Administrator`.

5. Verify the local key and Tailscale connection:

```powershell
Test-Path $keyPath
ssh-add -l
tailscale status
tailscale ping $server
```

Expected results:

- `Test-Path` prints `True`.
- `ssh-add -l` lists the key fingerprint. If it says the agent has no
  identities, run `ssh-add $keyPath` and enter the key's passphrase.
- `tailscale status` lists the target server.
- `tailscale ping` receives a reply from the target server.

If the full MagicDNS name does not resolve, do not continue. Confirm MagicDNS
is enabled, both PCs are connected to the same tailnet, and `$server` includes
both the machine name and tailnet domain.

##### E4. Confirm passwordless SSH from developer to target

**Run on: Developer/operator PC — the same normal PowerShell window.**

```powershell
& "$env:WINDIR\System32\OpenSSH\ssh.exe" `
    -i $keyPath `
    -o BatchMode=yes `
    -o StrictHostKeyChecking=accept-new `
    "$sshUser@$server" `
    "whoami"
```

Expected result: the command prints the target server account name and returns
to PowerShell without requesting the target user's Windows password.

If it asks for `<user>@<server>'s password`, the target server did not accept
the public key. Do not disable SSH password authentication and do not continue
to fleet setup. Recheck section C:

- The public `.pub` key is in
  `C:\ProgramData\ssh\administrators_authorized_keys` on the target server.
- The private key in `$keyPath` is the matching key on the developer PC.
- The authorized-key file contains one complete `ssh-ed25519 ...` line.
- Its ACL allows only SYSTEM and Administrators.
- The `sshd` service was restarted after the key was added.

##### E5. Create `deploy\sites.json` on the developer PC

**Do on: Developer/operator PC**, in the repository root.

Copy `deploy\sites.example.json` to `deploy\sites.json`. The destination file
is gitignored. Edit it so it contains the actual values already tested in E4:

```json
{
  "sites": [
    {
      "name": "cebu",
      "group": "canary",
      "host": "smartwagers-cebu.tail287ec9.ts.net",
      "user": "Administrator",
      "port": 22,
      "remote_root": "C:/SmartWagers/GameFowl",
      "ssh_key": "C:/Users/David/.ssh/smartwagers_cebu"
    }
  ]
}
```

Field meanings:

- `name` — short venue name passed to `fleet.py --site`.
- `group` — use `canary` for the first site upgraded; use `fleet` for the
  remaining sites.
- `host` — the target server's full MagicDNS name, not only
  `tail287ec9.ts.net`.
- `user` — the target server Windows account that passed the SSH test.
- `remote_root` — SmartWagers installation folder on the target server.
- `ssh_key` — private-key path on the developer PC. Use forward slashes in
  JSON.

Do not put a Windows password, Tailscale auth key, public-key text, or
private-key text in `sites.json`.

##### E6. Run the final checks

**Run on: Developer/operator PC — normal PowerShell in the repository root.**

```powershell
python deploy/fleet.py preflight --sites deploy/sites.json --site $venue
```

The command must complete successfully. Then, on the developer/operator PC:

1. Open `http://smartwagers-cebu.tail287ec9.ts.net:8080/health/ready/` and
   confirm `"ok": true`.
2. Open `http://smartwagers-cebu.tail287ec9.ts.net:8080/login` and sign in.
3. Confirm a superuser can open the master-lock page.

Finally, on a **teller PC**, open `http://192.168.1.10:8080/login` and confirm
the LAN login still works.

Do not continue to the first remote release until all five checks pass:
Tailscale ping, passwordless batch SSH, fleet preflight, remote health, and LAN
login. If Tailscale is unavailable later, use the USB path in section 3.2.

## 3. Update an existing deployment

Stop new bets and wait until tellers are idle. Leave the server powered on. The apply stops Daphne, backs up PostgreSQL when there are migrations, then starts Daphne again.

### 3.1 Remote update (normal path)

**Run on: Developer/operator PC**, in the repository root, with Tailscale
connected and the section 2.6 checks already passing. `preflight` opens SSH and
confirms the target server has `manage.py`. `deploy` copies the package to
`C:\SmartWagers\incoming\<package>` on the target server and runs the same apply
engine as `APPLY_RELEASE.bat`. `verify` reads
`deploy\.deployed_release.json` from the target server and compares the commit.

```bash
python deploy/fleet.py preflight --sites deploy/sites.json --site davao-1
python deploy/fleet.py deploy --sites deploy/sites.json --site davao-1 --package releases/SmartWagers-20261022-025246Z-4133eeb1
python deploy/fleet.py verify --sites deploy/sites.json --site davao-1 --expect-sha 4133eeb11eaf0515fb4087724e0267a710f866e9
```

For several venues, update the canary group first. A failed site stops the rest. Sites that already succeeded stay on the new release until you roll those sites back.

**Run on: Developer/operator PC**, in the repository root:

```bash
python deploy/fleet.py deploy --sites deploy/sites.json --group canary --package releases/<package>
python deploy/fleet.py verify --sites deploy/sites.json --group canary --expect-sha <commit>
python deploy/fleet.py deploy --sites deploy/sites.json --group fleet --package releases/<package>
python deploy/fleet.py status --sites deploy/sites.json
```

`--dry-run` prints the SSH and copy commands without connecting. Each attempt is appended to `deploy/fleet_history/<site>.jsonl`.

Deploying the same commit again does not copy or migrate a second time.

### 3.2 USB update (site is offline)

1. On the **developer/operator PC**, copy the field-kit folder to a USB drive.
2. Insert the USB drive into the **target server PC** at the venue.
3. On the **target server PC**, run
   `release\<package>\APPLY_RELEASE.bat` as Administrator.
4. On the **target server PC**, wait until it says the release was applied.
   Then open `http://localhost:8080/health/ready/`.

The USB installer uses the same apply engine as the remote deploy. Checksums are verified before files change.

### 3.3 Site files were edited by hand

Export an inventory before building the corrective package:

**Run on: Target server PC**, in an Administrator Command Prompt:

```bat
deploy\13_export_server_inventory.bat E:\server_inventory.json
```

Copy `E:\server_inventory.json` to the developer/operator PC.

**Run on: Developer/operator PC**, in the repository root:

```bash
python deploy/build_release.py --inventory /path/to/server_inventory.json --output releases --skip-checks
```

Apply that package with section 3.1 or 3.2. It still refuses to replace `.env`, the database, and the master-lock state.

### 3.4 After every update

- **Developer/operator PC:** Open
  `http://<magicdns-name>:8080/health/ready/`; it returns `"ok": true`.
- **Developer/operator PC:** Open `http://<magicdns-name>:8080/health/`; it
  shows the new `app_version` and `commit_sha`.
- **Target server PC or approved admin workstation:** Confirm admin login and
  the display board work.
- **Teller PC:** Place one test bet and print one receipt.
- **Teller PC:** If the receipt fails, reinstall that PC's print agent from
  **Admin → Print Agent**. An old teller agent does not roll the server back.

Record a teller that was updated:

**Run on: Target server PC**, from `C:\SmartWagers\GameFowl`:

```bat
python deploy\record_teller_agent.py --host TELLER-1 --version 1.13.2-shared-printer
```

## 4. If the update fails

The installer restores the previous code and the pre-migration database backup, then writes `deploy\.last_deploy_failure.json`. Daphne is started again on the restored code.

If the server is still down:

**Run on: Target server PC**, from `C:\SmartWagers\GameFowl` in an Administrator
Command Prompt:

```bat
python deploy\apply_engine.py --rollback --target C:\SmartWagers\GameFowl
```

**Run on: Developer/operator PC**, in the repository root:

```bash
python deploy/fleet.py rollback --sites deploy/sites.json --site <venue>
python deploy/fleet.py collect-diagnostics --sites deploy/sites.json --site <venue>
```

Full restore steps are in [RECOVERY_RUNBOOK.md](RECOVERY_RUNBOOK.md).
