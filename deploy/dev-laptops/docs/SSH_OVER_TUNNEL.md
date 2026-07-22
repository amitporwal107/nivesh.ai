# SSH to both laptops over Cloudflare Tunnel

Reach either laptop from anywhere — no port forwarding, no public IP, no
inbound firewall rule — using the tunnels already running for the app and
NIDP stacks.

> **Read the security section first.** Done wrong, this publishes your
> laptops' SSH daemons to the internet. Done as written, Cloudflare
> authenticates every connection before a packet reaches your machine.

---

## The rule: never route `ssh://` without Cloudflare Access

A public hostname pointing at `ssh://localhost:22` is reachable by **anyone
who learns the hostname**. Cloudflare proxies the TCP stream; it does not
authenticate it. You would be exposing a login prompt on a laptop that holds
your repo, cloud tokens and a production-derived database.

Cloudflare Access fixes this properly: it authenticates at the edge, and an
unauthenticated request never reaches your laptop at all. It is free for
small teams and takes about two minutes to set up.

**Do not skip step 3.**

---

## 1. Enable the SSH server on each laptop (Windows)

Run in an **Administrator PowerShell** on *both* laptops:

```powershell
# Install the OpenSSH server feature
Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0

# Start it, and start it on every boot
Start-Service sshd
Set-Service -Name sshd -StartupType Automatic

# Confirm
Get-Service sshd
```

Verify locally before involving the tunnel — if this fails, nothing later
will work:

```powershell
ssh localhost          # expect a password prompt (Ctrl-C out)
```

### Key-only login (recommended)

Password auth over a tunnel is still password auth. Prefer keys.

On the machine you connect *from*:

```bash
ssh-keygen -t ed25519 -C "laptop-access"
```

Then on **each laptop**, paste the public key into
`C:\Users\<you>\.ssh\authorized_keys`. For an **administrator** account
Windows uses a different file — this trips everyone up:

```
C:\ProgramData\ssh\administrators_authorized_keys
```

That file must be owned by Administrators with inheritance disabled:

```powershell
icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r
icacls C:\ProgramData\ssh\administrators_authorized_keys /grant "Administrators:F" /grant "SYSTEM:F"
```

Once keys work, disable password auth in `C:\ProgramData\ssh\sshd_config`:

```
PasswordAuthentication no
PubkeyAuthentication yes
```

then `Restart-Service sshd`.

---

## 2. Add an `ssh://` route to each tunnel

You already run one tunnel per laptop. Add a second route to each — **not**
a second replica of a shared tunnel (see the README's tunnel-topology note
for why that breaks).

| Laptop | Tunnel | Hostname | Service |
|---|---|---|---|
| 1 | `nivesh-copilot-l1` | `ssh.dev.niveshcopilot.com` | `ssh://localhost:22` |
| 2 | `nivesh-copilot-l2` | `ssh.nidp.niveshcopilot.com` | `ssh://localhost:22` |

Dashboard → **Networks → Tunnels → &lt;tunnel&gt; → Routes → Add route**:
type **Published application**, service **SSH**, target `localhost:22`.

---

## 3. Put Cloudflare Access in front (REQUIRED)

Dashboard → **Zero Trust → Access → Applications → Add an application**:

1. Type: **Self-hosted**
2. Application domain: `ssh.dev.niveshcopilot.com` (repeat for the second)
3. Policy:
   - Name: `laptop-ssh`
   - Action: **Allow**
   - Include → **Emails** → your address (e.g. `aporwal107@gmail.com`)
4. Save.

Now Cloudflare demands a login before any TCP reaches the laptop. Add more
`Include` rules for anyone else who needs in; remove them to revoke, with no
change on the laptop itself.

Verify the gate is live — from a machine that is **not** logged in:

```bash
curl -sI https://ssh.dev.niveshcopilot.com | head -3
```

Expect a `302` to `cloudflareaccess.com`. If you get anything else, the
policy is not attached and the route is exposed — fix before continuing.

---

## 4. Configure the client

Install `cloudflared` on the machine you connect from, then add to
`~/.ssh/config`:

```sshconfig
Host laptop1
    HostName ssh.dev.niveshcopilot.com
    User amitp
    ProxyCommand cloudflared access ssh --hostname %h

Host laptop2
    HostName ssh.nidp.niveshcopilot.com
    User amitp
    ProxyCommand cloudflared access ssh --hostname %h
```

Connect:

```bash
ssh laptop1
ssh laptop2
```

First connection opens a browser for the Access login; the token is cached
for the session duration you configured.

---

## 5. GitHub Actions deployment (service token)

The email policy in step 3 requires a browser login, which a CI runner cannot
do. For automated deploys, add a **service token** — a non-interactive
credential Access accepts in place of a human login.

### Create the token

Zero Trust → **Access → Service Auth → Service Tokens → Create Service Token**

- Name: `github-actions-laptop-deploy`
- Copy the **Client ID** and **Client Secret** now — the secret is shown once.

### Let the token through the policy

Edit each SSH application from step 3 → **Add a policy**:

- Name: `ci-deploy`
- Action: **Service Auth**  ← not "Allow"
- Include → **Service Token** → `github-actions-laptop-deploy`

Keep your email policy alongside it. Humans use one, CI the other, and you
can revoke either independently.

> Action **must** be `Service Auth`. An `Allow` policy with a service token
> still expects an identity and the runner will hang until it times out.

### Repo secrets

Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `LAPTOP_SSH_USER` | Windows username on both laptops |
| `LAPTOP_SSH_KEY` | private key (the public half is on the laptops) |
| `LAPTOP1_SSH_HOST` | `ssh.dev.niveshcopilot.com` |
| `LAPTOP2_SSH_HOST` | `ssh.nidp.niveshcopilot.com` |
| `LAPTOP1_REPO_PATH` | e.g. `/c/Users/amitp/localdeployment/nivesh.ai` |
| `LAPTOP2_REPO_PATH` | e.g. `/c/Users/amitp/localdeployment/nivesh.ai` |
| `CF_ACCESS_CLIENT_ID` | service token Client ID |
| `CF_ACCESS_CLIENT_SECRET` | service token Client Secret |

Use a **dedicated deploy key**, not your personal one — it lives in GitHub and
should be revocable without disturbing your own access.

### Run it

`.github/workflows/deploy-laptops.yml` → **Run workflow**, pick
`laptop1` / `laptop2` / `both`, and whether to rebuild images.

It checks out `dev`, installs cloudflared, opens an SSH session through
Access, resets the laptop's checkout to `origin/dev`, runs `up.sh`, and
verifies the edge responds. Credentials are scrubbed in an `always()` step.

**Manual trigger only, by design.** A laptop is often asleep, offline or on
another network; firing on every push to `dev` would produce constant red
builds that mean nothing. The workflow fails fast with a clear message when a
laptop is unreachable rather than hanging.

---

## What this gives you

```bash
# tail the stack from anywhere
ssh laptop1 'cd localdeployment/nivesh.ai/deploy/dev-laptops/laptop1-app && docker compose logs -f --tail 50'

# push the pg dump straight from nidp-stack-vm to laptop 2
scp -o ProxyCommand="cloudflared access ssh --hostname ssh.nidp.niveshcopilot.com" \
    /opt/nidp/dumps/nidp_staging_20260719.dump \
    amitp@ssh.nidp.niveshcopilot.com:localdeployment/.../laptop2-nidp/dumps/
```

That `scp` is an alternative to the `/upload/` endpoint — it needs no nginx
changes and reuses the Access policy you just created, but it is slower for
a 2.0 GB file than a plain PUT.

---

## Troubleshooting

**`ssh: connect to host ... port 22: Connection refused`** — `sshd` is not
running on the laptop. `Get-Service sshd` on that machine.

**Browser opens every time** — Access session duration is short. Zero Trust
→ Settings → Authentication → session duration (24h is reasonable).

**`kex_exchange_identification: Connection closed`** — the route is
`http://` not `ssh://`. Cloudflare is speaking HTTP to an SSH daemon.

**Permission denied (publickey)** for an admin account — the key is in the
wrong file. Admin accounts read
`C:\ProgramData\ssh\administrators_authorized_keys`, not the user's
`.ssh\authorized_keys`. See step 1.

**Works without logging in** — Access is not attached. Re-check step 3
immediately; the daemon is exposed.

---

## Turning it off

Delete the `ssh.*` routes from both tunnels, and on each laptop:

```powershell
Stop-Service sshd
Set-Service -Name sshd -StartupType Disabled
```

The app and NIDP routes are unaffected.
