# Argo CD Instance

Helm + Kustomize para a instalação HA do Argo CD (a partir da v3.3.0).

- **Helm** (`argo-cd` chart) – instala o ArgoCD com os valores de `base/values.yaml` + overlay.
- **Kustomize** – recursos extras que o Helm não gerencia (SealedSecret da senha admin).

## Overlays

Um por overlay do lab (`broetec-core`, `broetec-storage`, `broetec-monitor` e os
overlays locais), gerados a partir de `overlays/_template/`. O hostname é
`argo.<domínio do overlay>`.

## Como aplicar (deploy local / bootstrap)

A partir da 3.2, é **obrigatório** usar Server-Side Apply (CRD do ApplicationSet excede o limite do client-side apply).
Use sempre o release name `argocd`; a Application homônima depende desse padrão e evita duplicação por nomes divergentes.

```bash
# 1. Instalar/atualizar o chart Helm
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm upgrade --install argocd argo/argo-cd --version 9.4.10 \
  --namespace argocd --create-namespace \
  -f k8s/core/argocd/base/values.yaml \
  -f k8s/core/argocd/overlays/<overlay>/values.yaml

# 2. Aplicar recursos extras (SealedSecret da senha admin)
kubectl apply -k k8s/core/argocd/overlays/<overlay> --server-side --force-conflicts
```

### Se a instance for deployada por uma Application do Argo CD

Use a Application definida em `applications/` (já inclui `ServerSideApply=true`). A Application usa multi-source: Helm chart + repoData (values) + Kustomize (extras). Ver [`applications/README.md`](../applications/README.md). No lab esses passos são executados pelo role [`04_deploy_k8s`](../../../provisioning/roles/04_deploy_k8s/README.md).

## HTTPRoute (UI via Gateway API)

O acesso à UI do Argo CD é feito via HTTPRoute, configurado no Helm values (`server.httproute`). O base aponta para o Gateway `public` (namespace `cilium`, listener `https`) e o overlay define o hostname via `global.domain`.

## Senha admin (SealedSecret)

O Helm cria o `argocd-secret` com os campos internos (como `server.secretkey`). O SealedSecret faz **merge** (annotation `patch: "true"`) para definir apenas o campo `admin.password`, sem sobrescrever o resto.

No lab cada overlay traz um `admin-secret.yaml` didático (senha `broetec`); o
role `04_deploy_k8s` o sela em `admin-sealedsecret.yaml` com a chave BYOK de
`env/<overlay>/` a cada deploy. Para trocar a senha:

```bash
cd k8s/core/argocd/overlays/<overlay>

# 1. Gerar o hash bcrypt da senha
HASH=$(htpasswd -nbBC 10 "" 'sua-senha' | tr -d ':\n' | sed 's/$2y/$2a/')

# 2. Editar admin-secret.yaml: substituir o hash e atualizar admin.passwordMtime

# 3. Reenviar (sela e publica no Git local da VM)
make k8s-push OVERLAY=<overlay>
```

O `admin-sealedsecret.yaml` não é versionado: depende da chave BYOK de cada
máquina. Em produção, sele com a chave do cluster e versione o SealedSecret.

## Pré-requisitos por overlay

Além da senha admin acima, veja os arquivos `.example` em cada overlay.
