## Parte 3 - Deploy com o repositório `k8s-core`

> **Pré-requisito:** cluster RKE2 já instalado e acessível (`k`/`kubectl` funcionando no nó ou via workstation).

### 3.0 Aplicar configurações base Cilium (priorityclasses + Cilium)
```bash
k apply --server-side -k k8s/cluster-config/overlays/<environment_overlay>
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
  -f k8s/sealed-secrets/base/values.yaml \
  -f k8s/sealed-secrets/overlays/<environment_overlay>/values.yaml
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
  -f k8s/cert-manager/base/values.yaml \
  -f k8s/cert-manager/overlays/<environment_overlay>/values.yaml

k apply -k k8s/cert-manager/overlays/<environment_overlay>
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
  -f k8s/argocd/base/values.yaml \
  -f k8s/argocd/overlays/<environment_overlay>/values.yaml

k apply -k k8s/argocd/overlays/<environment_overlay>
```

Troubleshooting: Caso o Cilium não aplique as alterações automaticamente, você pode forçar o reinício do operador com o comando abaixo:
```bash
k rollout restart deployment -n kube-system cilium-operator 
```
