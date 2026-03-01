# k3s Single-Node AWX Cluster

GitOps-driven single-node k3s cluster running [AWX](https://github.com/ansible/awx) on Raspberry Pi `ktmb1-g-srv-003.iot.ktmb1.net`.

| Component | Tool |
|---|---|
| Kubernetes | k3s |
| GitOps | Flux |
| Secrets | External Secrets Operator + AWS Secrets Manager |
| Storage | k3s local-path provisioner |
| Database | CloudNativePG (PostgreSQL) with R2 backups |
| Automation | AWX (Ansible Automation Platform) |
| Network | Tailscale Operator |

## Prerequisites

- Raspberry Pi with Ubuntu/Debian (ARM64) accessible at `ktmb1-g-srv-003.iot.ktmb1.net`
- SSH key-based access configured for the target host
- [Ansible](https://docs.ansible.com/ansible/latest/installation_guide/) installed locally
- [kubectl](https://kubernetes.io/docs/tasks/tools/) installed locally
- [Flux CLI](https://fluxcd.io/flux/installation/#install-the-flux-cli) installed locally
- GitHub account with a personal access token (for Flux bootstrap)
- AWS account with access to Secrets Manager

## 1. Prepare AWS Secrets

Create the following secrets in AWS Secrets Manager:

| Secret Name | Description |
|---|---|
| `k3s-sno/awx/admin-password` | AWX admin user password |
| `k3s-sno/awx/postgres-password` | PostgreSQL database password |
| `k3s-sno/awx/secret-key` | AWX secret key for encryption |

```bash
aws secretsmanager create-secret --name k3s-sno/awx/admin-password \
  --secret-string "your-admin-password"

aws secretsmanager create-secret --name k3s-sno/awx/postgres-password \
  --secret-string "your-postgres-password"

aws secretsmanager create-secret --name k3s-sno/awx/secret-key \
  --secret-string "$(openssl rand -hex 32)"
```

## 2. Install k3s

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml
ansible-playbook playbooks/k3s-install.yml
```

After installation, set up your kubeconfig:

```bash
export KUBECONFIG=$(pwd)/kubeconfig
kubectl get nodes
```

## 3. Create AWS Credentials Bootstrap Secret

This secret is required by the External Secrets Operator to authenticate with AWS Secrets Manager. It must be created manually before Flux deploys ESO.

```bash
kubectl create namespace external-secrets

kubectl create secret generic aws-credentials \
  --namespace external-secrets \
  --from-literal=access-key-id=YOUR_AWS_ACCESS_KEY_ID \
  --from-literal=secret-access-key=YOUR_AWS_SECRET_ACCESS_KEY
```

## 4. Push to GitHub and Bootstrap Flux

```bash
# Push this repo to GitHub
git remote add origin git@github.com:YOUR_USER/k3s-sno.git
git push -u origin main

# Bootstrap Flux
flux bootstrap github \
  --owner=YOUR_USER \
  --repository=k3s-sno \
  --path=kubernetes/bootstrap/flux \
  --personal \
  --branch=main
```

Flux will:
1. Install its controllers on the cluster
2. Sync the repository
3. Deploy External Secrets Operator
4. Deploy AWX Operator and the AWX instance (after ESO is ready)

## 5. Monitor Deployment

```bash
# Watch Flux reconciliation
flux get kustomizations --watch

# Check AWX namespace
kubectl -n awx get pods --watch

# Check AWX operator logs
kubectl -n awx logs -f deployment/awx-operator-controller-manager
```

## 6. Access AWX

Once all pods are running:

**AWX:** `http://ktmb1-g-srv-003.iot.ktmb1.net:30080`
- **Username:** `admin`
- **Password:** The value stored in `k3s-sno/awx/admin-password` in AWS Secrets Manager

## Repository Structure

```
k3s-sno/
├── ansible/                          # k3s installation automation
│   ├── ansible.cfg
│   ├── inventory/hosts.yml
│   ├── requirements.yml
│   └── playbooks/k3s-install.yml
├── kubernetes/
│   ├── bootstrap/flux/               # Flux bootstrap (GitRepo + sync)
│   ├── flux/config/                  # Top-level cluster Kustomization
│   └── apps/
│       ├── external-secrets/         # ESO operator + ClusterSecretStore
│       ├── cloudnative-pg/           # CNPG operator + shared PostgreSQL cluster
│       ├── coredns/                  # Custom CoreDNS config (Tailscale MagicDNS)
│       ├── tailscale/               # Tailscale Operator
│       └── awx/                      # AWX Operator + AWX instance
├── .gitignore
└── README.md
```

## Updating

All changes are GitOps-driven. To modify the deployment:

1. Edit the relevant YAML files in `kubernetes/apps/`
2. Commit and push to `main`
3. Flux will automatically reconcile changes (within ~10 minutes, or force with `flux reconcile source git flux-system`)

## Troubleshooting

**Flux not reconciling:**
```bash
flux get sources git
flux get kustomizations
flux logs
```

**AWX pods not starting:**
```bash
kubectl -n awx describe pod <pod-name>
kubectl -n awx get events --sort-by='.lastTimestamp'
```

**ExternalSecret not syncing:**
```bash
kubectl -n awx get externalsecrets
kubectl -n external-secrets logs -f deployment/external-secrets
```

**Reset AWX admin password:**
Update the secret value in AWS Secrets Manager, then force a refresh:
```bash
kubectl -n awx annotate externalsecret awx-admin-password force-sync=$(date +%s) --overwrite
```
