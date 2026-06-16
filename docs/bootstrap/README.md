## Parte 3 - Deploy com o repositório `k8s-core`

> **Pré-requisito:** cluster RKE2 já instalado e acessível (`k`/`kubectl` funcionando no nó ou via workstation).

### 3.0 Aplicar configurações base Cilium (priorityclasses + Cilium)
```bash
k apply --server-side -k cluster-config/overlays/<environment_overlay>
```

### 3.1 Instalar Sealed Secrets (Helm) — antes do ArgoCD

Bootstrap manual; depois do deploy do ArgoCD (passo 5), a Application `sealed-secrets` passa a controlar o release (sync/upgrades).

Se você estiver reinstalando o controller (migração de cluster/DR), restaure a **master key** original antes de aplicar `SealedSecret`; caso contrário, uma nova key será gerada e os segredos antigos não serão descriptografados. Nesse cenário, aplique o backup (`kubectl apply -f master.key`) e, se necessário, reinicie os pods do controller para recarregar a key restaurada.

```bash
helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
helm repo update
helm upgrade --install sealed-secrets sealed-secrets/sealed-secrets \
  --namespace sealed-secrets \
  --create-namespace \
  --version 2.18.3 \
  -f sealed-secrets/base/values.yaml \
  -f sealed-secrets/overlays/<environment_overlay>/values.yaml
```

### 3.2 Instalar Cert-Manager (Helm) — antes do ArgoCD

Bootstrap manual; depois do deploy do ArgoCD (passo 5), a Application `cert-manager` passa a controlar o release (sync/upgrades).
```bash
helm repo add cert-manager https://charts.jetstack.io
helm repo update
helm upgrade --install cert-manager cert-manager/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.19.3 \
  -f cert-manager/base/values.yaml \
  -f cert-manager/overlays/<environment_overlay>/values.yaml

k apply -k cert-manager/overlays/<environment_overlay>
```

### 3.3 Instalar ArgoCD (Helm) — bootstrap

Bootstrap manual; depois do primeiro sync, a Application `argocd` passa a controlar o release (sync/upgrades).
Use o nome de release `argocd` no bootstrap para evitar instalação duplicada do Argo CD.
```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --version 9.4.10 \
  -f argocd/base/values.yaml \
  -f argocd/overlays/<environment_overlay>/values.yaml

k apply -k argocd/overlays/<environment_overlay>
```

Troubleshooting: Caso o Cilium não aplique as alterações automaticamente, você pode forçar o reinício do operador com o comando abaixo:
```bash
k rollout restart deployment -n kube-system cilium-operator 
```

#### 3.4 local-path-provisioner: deploy e resolução de `mkdir: Permission denied`

Aplicável apenas ao **RKE2**. O k3s inclui o local-path-provisioner como componente nativo (`storageClass: local-path`, `reclaimPolicy: Delete`) e não requer configuração adicional.

No RKE2, o deploy é feito pela role Ansible `03_install_rke2` imediatamente após o cluster estar Ready. Activa-o no inventory:

```yaml
# provisioning/inventory/<overlay>/group_vars/all/90_local.yml
rke2_local_path_dir: /opt/local-path-provisioner   # directório no nó (mkdir + SELinux)
rke2_local_path_deploy: true                        # namespace PSA + Helm chart
rke2_local_path_overlay: broetec-core              # default = inventory_hostname
```

O Ansible executa automaticamente:

1. **Preparação do nó** (`tasks/local_path.yml`, antes do install do RKE2) — cria o directório, aplica `chmod 1777` e o contexto SELinux `container_file_t` exigido pelo Rocky Linux.

2. **Namespace `local-path-storage` com PSA `privileged`** + **Helm chart** (`tasks/local_path_deploy.yml`, após cluster Ready) — aplica o manifesto de `k8s/local-path-provisioner/overlays/<overlay>` via `kubectl apply -k` e faz o deploy do chart `rancher/local-path-provisioner` com os valores de `k8s/local-path-provisioner/base/values.yaml` e do overlay.

   > O `priorityClassName: "pc-0-infra-core"` do `base/values.yaml` é sobreposto para `""` no bootstrap; o ArgoCD reconcilia o valor correcto quando tomar controlo do release após o deploy do `cluster-config`.

Para aplicar manualmente num nó existente:

```bash
NODE_PATH="/opt/local-path-provisioner"
sudo mkdir -p "$NODE_PATH"
sudo chmod 1777 "$NODE_PATH"
sudo chcon -Rt container_file_t "$NODE_PATH"
# namespace + PSA:
kubectl apply -k k8s/local-path-provisioner/overlays/<overlay>
```

### 3.5 Deploy das demais aplicações (app-of-apps)

```bash
k apply -k applications/overlays/<environment_overlay>
```
