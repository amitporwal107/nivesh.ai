# deploy/keys/ — SSH Key Store

This folder is **gitignored**. Drop your private keys here and they will never be committed.

## Expected files

| File | Purpose | Used by |
|---|---|---|
| `nivesh-devops-deploy` | CI/CD private key → both VMs | Jenkins, manual deploys |
| `nivesh-devops-deploy.pub` | Public key (registered to GCP OS Login) | Reference only |
| `nidp-sa-deploy` | NIDP orchestrator → nidp-stack-vm | Backfill/replay triggers |
| `nidp-sa-deploy.pub` | Public key | Reference only |
| `nidp-admin-deploy` | Break-glass emergency key (passphrase protected) | Emergency SSH only |
| `nidp-admin-deploy.pub` | Public key | Reference only |

## How keys get here

Generated and registered by:

```bash
bash deploy/setup-iam.sh --confirm --ssh
```

Keys are written to `~/.ssh/nivesh/` by default. Copy them here if you want
them accessible from the repo directory:

```bash
cp ~/.ssh/nivesh/nivesh-devops-deploy     deploy/keys/
cp ~/.ssh/nivesh/nivesh-devops-deploy.pub deploy/keys/
cp ~/.ssh/nivesh/nidp-sa-deploy           deploy/keys/
cp ~/.ssh/nivesh/nidp-sa-deploy.pub       deploy/keys/
```

## Permissions

```bash
chmod 600 deploy/keys/nivesh-devops-deploy
chmod 600 deploy/keys/nidp-sa-deploy
chmod 600 deploy/keys/nidp-admin-deploy
```

## SSH usage

```bash
# OS Login username for the devops service account (sa_ + numeric unique ID)
# nivesh-devops@niveshdataintelligence.iam.gserviceaccount.com → sa_108611142161866522954

ssh -i deploy/keys/nivesh-devops-deploy sa_108611142161866522954@34.47.250.214  # nivesh-app-vm
ssh -i deploy/keys/nivesh-devops-deploy sa_108611142161866522954@34.93.60.254    # nidp-stack-vm
```

## Jenkins setup

Add the private key at **Jenkins → Credentials → System → Global → Add Credential**:

```
Kind     : SSH Username with private key
ID       : nivesh-devops-vm-ssh
Username : sa_108611142161866522954
Key      : (paste contents of deploy/keys/nivesh-devops-deploy)
```
