# Argo CD Instance

Helm + Kustomize para a instalação HA do Argo CD (a partir da v3.3.0).

- **Helm** (`argo-cd` chart) – instala o ArgoCD com os valores de `base/values.yaml` + overlay.
- **Kustomize** – recursos extras que o Helm não gerencia (SealedSecret da senha admin).

## Overlays

- **storage** – storage

## Como aplicar (deploy local / bootstrap)

A partir da 3.2, é **obrigatório** usar Server-Side Apply (CRD do ApplicationSet excede o limite do client-side apply).
Use sempre o release name `argocd`; a Application homônima depende desse padrão e evita duplicação por nomes divergentes.

```bash
# 1. Instalar/atualizar o chart Helm
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd --version 9.4.10 \
  --namespace argocd --create-namespace \
  -f k8s/argocd/base/values.yaml \
  -f k8s/argocd/overlays/<overlay>/values.yaml

# 2. Aplicar recursos extras (SealedSecret do repo SSH)
kubectl apply -k k8s/argocd/overlays/<overlay> --server-side --force-conflicts
```

### Se a instance for deployada por uma Application do Argo CD

Use a Application definida em `applications/` (já inclui `ServerSideApply=true`). A Application usa multi-source: Helm chart + repoData (values) + Kustomize (extras). Para o mapa overlay → cluster e convenções ao acrescentar `dev`/`prod`, ver [`applications/README.md`](../applications/README.md).

## HTTPRoute (UI via Gateway API)

O acesso à UI do Argo CD é feito via HTTPRoute, configurado no Helm values (`server.httproute`). O base aponta para o Gateway `vpn` e o overlay define o hostname via `global.domain`.

## Senha admin (SealedSecret)

O Helm cria o `argocd-secret` com os campos internos (como `server.secretkey`). O SealedSecret faz **merge** (annotation `patch: "true"`) para definir apenas o campo `admin.password`, sem sobrescrever o resto.

**Antes do primeiro apply**, gere o `admin-sealedsecret.yaml`:

```bash
cd argocd/overlays/<overlay>   # ex.: storage

# 1. Gerar o hash bcrypt da senha
HASH=$(htpasswd -nbBC 10 "" 'sua-senha' | tr -d ':\n' | sed 's/$2y/$2a/')

# 2. Criar o secret a partir do example
cp admin-secret.yaml.example admin-secret.yaml
# Editar admin-secret.yaml: substituir o hash e o timestamp

# 3. Selar o secret
kubeseal --format yaml \
  --cert sealed-secrets/overlays/<overlay>/storage-pub.pem \
  < admin-secret.yaml > admin-sealedsecret.yaml
```

O `admin-sealedsecret.yaml` é commitado (criptografado). O `admin-secret.yaml` está no `.gitignore`.

## Pré-requisitos por overlay

Além da senha admin acima, veja os arquivos `.example` em cada overlay.
