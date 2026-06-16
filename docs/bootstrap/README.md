**Diagnóstico de performance do etcd**: detalhes no guia dedicado `docs/fine-tuning/README.md`.

### 2.3. Configurar o Cilium (HelmChartConfig)

O RKE2 aplica customizações ao chart do Cilium via **HelmChartConfig** usando o campo `valuesContent` (bloco YAML). O uso de `values` (objeto) não é aplicado corretamente. O `metadata.name` deve ser **rke2-cilium** (igual ao HelmChart empacotado).

**Versão do Cilium:** a versão padrão é definida pelo **chart empacotado** do RKE2 que você está usando; cada release do RKE2 traz um chart rke2-cilium com uma tag de imagem fixa. Para ver a versão em uso:  
`kubectl get ds -n kube-system cilium -o jsonpath='{.spec.template.spec.containers[0].image}'`  
ou `helm get values rke2-cilium -n kube-system`.

**Fixar outra versão:** neste guia estamos usando **v1.18.7** (agent e operator) por precaução: há um bug/regressão reportado ao atualizar de **1.18.7 → 1.19.1** que pode afetar acesso externo ao host (ex.: SSH) e conexões de saída do host. Referência: https://github.com/cilium/cilium/issues/44430.  
Ainda assim, é possível sobrescrever a imagem (agent e operator) via `valuesContent` para testar outra versão; use a **mesma tag** para agent e operator e, em geral, prefira manter a mesma minor (ou versões compatíveis documentadas).

O manifest deve ficar em `/var/lib/rancher/rke2/server/manifests/`. Com 1 réplica do operator evita-se conflito de portas (9234, 9963) em cluster de nó único.
```bash
sudo mkdir -p /var/lib/rancher/rke2/server/manifests

cat <<'EOF' | sudo tee /var/lib/rancher/rke2/server/manifests/rke2-cilium-config.yaml
apiVersion: helm.cattle.io/v1
kind: HelmChartConfig
metadata:
  name: rke2-cilium
  namespace: kube-system
spec:
  valuesContent: |-
    k8sServiceHost: "PLACEHOLDER"
    k8sServicePort: 6443
    operator:
      replicas: 1
      image:
        override: quay.io/cilium/operator-generic:v1.18.7

    image:
      repository: quay.io/cilium/cilium
      tag: v1.18.7

    kubeProxyReplacement: true

    gatewayAPI:
      enabled: true
      gatewayClass:
        create: "false"

    extraConfig:
      unmanaged-pod-watcher-interval: "15"

EOF
```



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

#### 3.4 local-path-provisioner: `mkdir: Permission denied` no helper pod

O *helper pod* cria diretórios sob o path do `nodePathMap` (ex.: `/opt/local-path-provisioner/...`). Em RKE2/Rocky com **Pod Security Admission** restritivo, o pod pode correr sem privilégios suficientes e falhar com `Permission denied`, seguido de *timeout* no provisionamento.

1. **Namespace com PSA `privileged`** — o manifesto está em `local-path-provisioner/cluster/base/namespace.yaml` e é aplicado pela mesma Application **`local-path-provisioner`** (terceira fonte Kustomize: `local-path-provisioner/cluster/overlays/<environment>`). Não depende do `cluster-config`. Se o namespace já existir sem estas labels, faz sync dessa Application ou `kubectl label namespace local-path-storage ...` conforme esse ficheiro.

2. **Permissões no nó** — em cada nó, isto é tipicamente necessário **uma vez** (ou sempre que mudares o caminho do `nodePathMap`).

   ```bash
   NODE_PATH="/opt/local-path-provisioner" # ou o path que aparece no log/config do provisioner
   sudo mkdir -p "$NODE_PATH"
   sudo chmod 1777 "$NODE_PATH"
   sudo chcon -Rt container_file_t "$NODE_PATH"
   ```

   (Ajusta o path se não for `/opt/local-path-provisioner`.)

### 3.5 Deploy das demais aplicações (app-of-apps)

```bash
k apply -k applications/overlays/<environment_overlay>
```
