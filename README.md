# k3s Single-Node AWX Cluster

GitOps-driven single-node k3s cluster running [AWX](https://github.com/ansible/awx) on Raspberry Pi `ktmb1-g-srv-003.iot.ktmb1.net`.

| Component | Tool |
|---|---|
| Kubernetes | k3s |
| GitOps | Flux |
| Secrets | External Secrets Operator + AWS Secrets Manager |
| Local Secrets | SOPS + age |
| Storage | k3s local-path provisioner |
| Database | CloudNativePG (PostgreSQL) with R2 backups |
| Automation | AWX (Ansible Automation Platform) |
| Network | Tailscale Operator |
| Dev Env | mise + Taskfile |

## Prerequisites

- Raspberry Pi with Ubuntu/Debian (ARM64) accessible at `ktmb1-g-srv-003.iot.ktmb1.net`
- SSH key-based access configured for the target host
- [Ansible](https://docs.ansible.com/ansible/latest/installation_guide/) installed locally
- [mise](https://mise.jdx.dev/) installed and activated in your shell
- GitHub account with a personal access token (for Flux bootstrap)
- AWS account with access to Secrets Manager

## Developer Setup

All CLI tools (kubectl, flux, helm, sops, age, task, yq, jq) are managed by mise. One-time setup:

```bash
mise trust && mise install
```

Generate an age key for SOPS encryption (one-time):

```bash
task bootstrap:age
```

Copy the public key printed to stdout into `.sops.yaml`, replacing the placeholder.

Edit `.env.sops.yaml` with a regular editor and fill in your actual secret values:

```bash
nano .env.sops.yaml
```

Then encrypt the file in place (first time only):

```bash
sops --encrypt --in-place .env.sops.yaml
```

From this point on, use `sops .env.sops.yaml` to edit -- it decrypts into your editor and re-encrypts on save.

List all available tasks:

```bash
task --list
```

## 1. Prepare AWS Secrets

Create the following secrets in AWS Secrets Manager:

| Secret Name | Description |
|---|---|
| `k3s-sno/awx/admin-password` | AWX admin user password |
| `k3s-sno/awx/postgres-password` | PostgreSQL database password |
| `k3s-sno/awx/secret-key` | AWX secret key for encryption |
| `k3s-sno/awx/ssh-private-key` | SSH private key for managed hosts |
| `k3s-sno/tailscale/oauth-client-id` | Tailscale OAuth client ID (for dynamic inventory) |
| `k3s-sno/tailscale/oauth-client-secret` | Tailscale OAuth client secret (for dynamic inventory) |

```bash
aws secretsmanager create-secret --name k3s-sno/awx/admin-password \
  --secret-string "your-admin-password"

aws secretsmanager create-secret --name k3s-sno/awx/postgres-password \
  --secret-string "your-postgres-password"

aws secretsmanager create-secret --name k3s-sno/awx/secret-key \
  --secret-string "$(openssl rand -hex 32)"

aws secretsmanager create-secret --name k3s-sno/awx/ssh-private-key \
  --secret-string "$(cat ~/.ssh/id_ed25519)"

aws secretsmanager create-secret --name k3s-sno/tailscale/oauth-client-id \
  --secret-string "your-oauth-client-id"

aws secretsmanager create-secret --name k3s-sno/tailscale/oauth-client-secret \
  --secret-string "tskey-client-..."
```

## 2. Install k3s

```bash
task ansible:deps
task ansible:k3s
```

After installation, verify the node (mise automatically sets `KUBECONFIG`):

```bash
kubectl get nodes
```

## 3. Create AWS Credentials Bootstrap Secret

This secret is required by the External Secrets Operator to authenticate with AWS Secrets Manager. It must be created before Flux deploys ESO.

```bash
task bootstrap:secrets
```

## 4. Push to GitHub and Bootstrap Flux

```bash
# Push this repo to GitHub (first time only)
git remote add origin git@github.com:amasolov/k3s-sno.git
git push -u origin main

# Bootstrap Flux
task bootstrap:flux
```

Flux will:
1. Install its controllers on the cluster
2. Sync the repository
3. Deploy External Secrets Operator
4. Deploy AWX Operator and the AWX instance (after ESO is ready)

## 5. Monitor Deployment

```bash
# Flux status (Kustomizations + HelmReleases)
task flux:status

# Watch pods across all namespaces
task k8s:pods

# Tail Flux logs
task flux:logs

# AWX-specific events
task k8s:events NS=awx
```

## 6. Configure AWX (Infrastructure as Code)

AWX configuration is defined as code in `ansible/playbooks/awx-config.yml`. The playbook uses the `awx.awx` collection to create all resources (organizations, projects, inventories, credentials, job templates, etc.) via the AWX REST API.

```bash
task ansible:awx-config
```

This creates:
- **KTMB1** organization with **Home Lab** and **Home Assistant** inventories
- **Home Assistant** inventory is dynamically populated from the Tailscale API, grouped by ACL tags
- **Home Lab SSH** machine credential (key from AWS Secrets Manager)
- **KTMB1** project pointing at this Git repo
- **Install k3s** job template
- **AWX Self-Configure** job template (so AWX can re-apply its own config)

Tag your Tailscale devices by function to have them auto-grouped in the inventory:
- `tag:ha-server` -> group `ha_server`
- `tag:display-pi` -> group `display_pi`
- Add any custom tags as needed; `tag:foo-bar` becomes group `foo_bar`

To add resources, edit the variable lists in `awx-config.yml` and re-run `task ansible:awx-config`.

The self-configure job template lets AWX re-run this playbook against itself. It requires an Execution Environment with the `awx.awx` and `amazon.aws` collections installed.

## 7. Access AWX

Once all pods are running:

**AWX:** `https://awx.ktmb1.net` (via NGINX Proxy Manager -> `http://ktmb1-g-srv-003:30080`)
- **Username:** `admin`
- **Password:** The value stored in `k3s-sno/awx/admin-password` in AWS Secrets Manager

## Repository Structure

```
k3s-sno/
├── .editorconfig                    # Editor formatting rules
├── .env.sops.yaml                   # Encrypted local secrets (AWS, GitHub)
├── .gitignore
├── .mise.toml                       # Tool versions (kubectl, flux, sops, etc.)
├── .sops.yaml                       # SOPS encryption rules
├── Taskfile.yaml                    # Root task runner
├── .taskfiles/
│   ├── ansible/Taskfile.yaml        # ansible:deps, ansible:k3s, ansible:awx-config
│   ├── bootstrap/Taskfile.yaml      # bootstrap:age, bootstrap:secrets, bootstrap:flux
│   ├── cluster/Taskfile.yaml        # cluster:nuke, cluster:wait, cluster:init-fresh
│   ├── flux/Taskfile.yaml           # flux:reconcile, flux:status, flux:logs, flux:hr
│   └── k8s/Taskfile.yaml            # k8s:pods, k8s:events, k8s:logs, k8s:nodes
├── ansible/
│   ├── ansible.cfg
│   ├── requirements.yml             # Galaxy collections (awx.awx, amazon.aws, etc.)
│   ├── inventory/
│   │   ├── hosts.yml                # Managed host inventory
│   │   ├── awx_config.yml          # AWX API connection for config-as-code
│   │   └── tailscale_inventory.py  # Dynamic inventory from Tailscale API
│   └── playbooks/
│       ├── k3s-install.yml          # k3s cluster installation
│       ├── k3s-nuke.yml             # k3s uninstall and cleanup
│       └── awx-config.yml          # AWX configuration as code
├── kubernetes/
│   ├── bootstrap/flux/              # Flux bootstrap (GitRepo + sync)
│   ├── flux/config/                 # Top-level cluster Kustomization
│   └── apps/
│       ├── external-secrets/        # ESO operator + ClusterSecretStore
│       ├── cloudnative-pg/          # CNPG operator + shared PostgreSQL cluster
│       ├── coredns/                 # Custom CoreDNS config (Tailscale MagicDNS)
│       ├── tailscale/              # Tailscale Operator
│       └── awx/                     # AWX Operator + AWX instance
├── renovate.json
└── README.md
```

## Task Reference

| Task | Description |
|------|-------------|
| `task ansible:deps` | Install Ansible Galaxy collections |
| `task ansible:k3s` | Run k3s install playbook |
| `task ansible:awx-config` | Apply AWX configuration as code |
| `task bootstrap:age` | Generate age key pair (one-time) |
| `task bootstrap:secrets` | Create ESO bootstrap secret in-cluster |
| `task bootstrap:flux` | Bootstrap Flux into the cluster |
| `task flux:reconcile` | Force Flux to reconcile from Git |
| `task flux:status` | Show Kustomization + HelmRelease status |
| `task flux:hr` | Show all HelmReleases |
| `task flux:logs` | Tail Flux controller logs |
| `task k8s:pods` | Get pods (all NS, or `NS=awx`) |
| `task k8s:events NS=<ns>` | Get events for a namespace |
| `task k8s:logs NS=<ns> POD=<pod>` | Tail pod logs |
| `task k8s:nodes` | Show node status and resource usage |
| `task cluster:nuke` | Uninstall k3s and remove local kubeconfig |
| `task cluster:install` | Install k3s and fetch kubeconfig |
| `task cluster:bootstrap` | Create secrets + bootstrap Flux |
| `task cluster:wait` | Wait for Flux and AWX to become ready |
| `task cluster:init-fresh` | First-time setup: create empty DB (no R2 backup needed) |
| `task rebuild` | Full rebuild (install → bootstrap → wait), restores DB from R2 |
| `task nuke-rebuild` | Destroy cluster and rebuild from scratch, restores DB from R2 |
| `task reconcile` | Shortcut for `flux:reconcile` |

## Nuke & Rebuild

The CNPG cluster is configured to **automatically restore from the latest R2 backup** when recreated. After a nuke, your AWX data comes back seamlessly.

```bash
task nuke-rebuild
```

Or run each phase individually:

```bash
task cluster:nuke           # uninstall k3s, delete kubeconfig
task rebuild                # reinstall k3s, bootstrap Flux, wait for readiness
task ansible:awx-config     # configure AWX once it's ready
```

The nuke step runs the `k3s-nuke.yml` playbook which:
1. Executes `k3s-uninstall.sh` on the Pi
2. Removes leftover data directories (`/var/lib/rancher`, `/etc/rancher`, CNI)
3. Prunes container images
4. Deletes the local kubeconfig

### First-time setup (no R2 backup yet)

If the R2 bucket is empty (no prior backup exists), the recovery bootstrap will fail. Use `init-fresh` instead to create an empty database and take the first backup:

```bash
task cluster:install
task cluster:bootstrap
task cluster:init-fresh      # creates empty DB, triggers first backup
task cluster:wait
task ansible:awx-config
```

Once the first backup completes in R2, all subsequent `nuke-rebuild` cycles will restore automatically.

## Updating

All changes are GitOps-driven. To modify the deployment:

1. Edit the relevant YAML files in `kubernetes/apps/`
2. Commit and push to `main`
3. Flux will automatically reconcile changes (within ~10 minutes, or force with `task reconcile`)

## Troubleshooting

```bash
# Flux not reconciling
task flux:status
task flux:logs

# AWX pods not starting
task k8s:events NS=awx
task k8s:logs NS=awx POD=<pod-name>

# ExternalSecret not syncing
kubectl -n awx get externalsecrets
task k8s:logs NS=external-secrets POD=<eso-pod>

# Reset AWX admin password
# Update the value in AWS Secrets Manager, then:
kubectl -n awx annotate externalsecret awx-admin-password force-sync=$(date +%s) --overwrite

# Nuclear option — wipe and rebuild everything
task nuke-rebuild
```
