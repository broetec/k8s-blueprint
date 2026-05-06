# Atualização do RKE2

Guia para atualizar o RKE2 num **cluster de um único nó server** (caso deste repositório), preservando o etcd, o Cilium fixado por `HelmChartConfig` e o resto da *stack* (cert-manager, ArgoCD, sealed-secrets, etc.).

> **Premissa:** o procedimento abaixo cobre o setup descrito em `README.md` (1 servidor, sem agents, Cilium kpr + Gateway API). Para clusters HA (3 servers) há notas adicionais no fim do documento.

---

## 1) Antes de começar

### 1.1. Versão atual e versão alvo

```bash
rke2 --version
kubectl version --short
```

Anote a versão atual (ex.: `v1.34.7+rke2r1`).

### 1.2. Regras de *version skew*

O Kubernetes não suporta saltar versões *minor*. **Atualize uma minor de cada vez**:

- `v1.34.x` -> `v1.35.x`: OK.
- `v1.34.x` -> `v1.36.x`: **não suportado**, atualize primeiro para `v1.35.x`.

### 1.3. Ler as notas de upgrade

Antes de cada upgrade *minor*, abra:

- [Release notes do RKE2 da minor alvo](https://docs.rke2.io/release-notes/) (ex.: `v1.35.X`).
- [Kubernetes Urgent Upgrade Notes](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/) (ex.: `CHANGELOG-1.35.md`).
- Confirme se o **chart de Cilium empacotado** mudou de versão e se isso afeta o seu `HelmChartConfig`.

### 1.4. Janela de manutenção

Em cluster de um nó o `kube-apiserver` reinicia durante o upgrade (~30-90 s) e **alguns pods reiniciam** (kube-system e os que dependem do CNI/CRI). Planeie a janela em horário de baixo tráfego.

---

## 2) Backups obrigatórios

### 2.1. Snapshot manual do etcd

O RKE2 já agenda snapshots (`etcd-snapshot-schedule-cron` no `config.yaml`), mas tire um **snapshot extra** imediatamente antes do upgrade:

```bash
sudo rke2 etcd-snapshot save --name "pre-upgrade-$(date +%Y%m%d-%H%M)"

sudo ls -lah /var/lib/rancher/rke2/server/db/snapshots/ | tail -10
```

> **Nota:** se tiver `etcd-s3` ativo no `config.yaml`, o snapshot é replicado para o bucket. Caso contrário, copie o ficheiro mais recente para fora do nó (S3, NFS, scp para outra máquina) antes de prosseguir. Em VPS, é o que evita perda total se o disco partir.

### 2.2. Token, `config.yaml` e manifests para `~/rke2-backups`

O token é necessário para *restore* a partir de um snapshot (a mesma chave criptografa o *bootstrap* no datastore); o `config.yaml` e os manifests do servidor reproduzem a configuração do plano de controlo e do Cilium se for preciso reinstalar do zero.

Os três ficam num único diretório no `$HOME`, com `ownership` do utilizador atual e timestamp único — o `install` copia com as permissões certas sem ter de andar com `sudo cat | tee`:

```bash
mkdir -p ~/rke2-backups
DATE=$(date +%Y%m%d-%H%M)

sudo install -m 600 -o "$USER" -g "$USER" \
  /var/lib/rancher/rke2/server/token \
  ~/rke2-backups/token-${DATE}

sudo install -m 644 -o "$USER" -g "$USER" \
  /etc/rancher/rke2/config.yaml \
  ~/rke2-backups/config-${DATE}.yaml

sudo cp -a /var/lib/rancher/rke2/server/manifests ~/rke2-backups/manifests-${DATE}
sudo chown -R "$USER:$USER" ~/rke2-backups/manifests-${DATE}

ls -la ~/rke2-backups/
```

> **Atenção:** isto ainda está no **mesmo disco da VPS**. Para backup real, copie `~/rke2-backups/` (e o snapshot do passo 2.1, se não tiver `etcd-s3` ativo) para fora do nó — `scp`/`rsync` para outra máquina, ou para um bucket S3-compatível. O token em particular vale guardar também num gestor de segredos / cofre.

---

## 3) Escolher canal vs versão fixa

### 3.1. Canal `stable` (recomendado em produção)

```bash
INSTALL_RKE2_CHANNEL=stable
```

Pega na *patch* mais recente do canal estável (atualmente `v1.35.x`). Este repositório segue o canal `stable`.

### 3.2. Canal `v1.35` (fixar a *minor*, evita salto acidental)

```bash
INSTALL_RKE2_CHANNEL=v1.35
```

Garante que apanha sempre a *patch* mais recente da `v1.35.x`, mas nunca passa para `v1.36.x` automaticamente. Útil se preferir testar uma minor por uma janela de manutenção dedicada.

### 3.3. Versão exata (reproduzível)

```bash
INSTALL_RKE2_VERSION="v1.35.4+rke2r1"
```

Equivalente a *pin* explícito - escolha esta opção se quer que o upgrade seja determinístico (mesmo binário em DEV/STG/PRD). Lista de releases: <https://github.com/rancher/rke2/releases>.

---

## 4) Cilium e o `HelmChartConfig`

O RKE2 distribui um chart `rke2-cilium` empacotado. Cada release de RKE2 traz uma **versão default** desse chart (ex.: RKE2 `v1.34.7` -> Cilium `v1.18.x`; RKE2 `v1.35.4` -> Cilium `v1.19.x`).

Como o `HelmChartConfig` deste repositório (em `cluster-config/cilium/...` e no manifest aplicado em `/var/lib/rancher/rke2/server/manifests/rke2-cilium-config.yaml`) **fixa explicitamente** a tag das imagens (`image.tag: v1.18.7`, `operator.image.override: ...:v1.18.7`), o upgrade do RKE2 **não muda** a versão do Cilium em execução - apenas o *chart wrapper* é atualizado.

Recomendação:

1. **Primeiro upgrade**: RKE2 `v1.34.x` -> `v1.35.x` mantendo Cilium fixado em `v1.18.7`. Valida-se o data plane (Gateway API, kpr) com a versão de CNI já conhecida.
2. **Depois**, em janela separada, considerar atualizar o Cilium para `v1.19.x` (atenção ao [issue 44430](https://github.com/cilium/cilium/issues/44430), que afetava conexões saintes do host em `1.18.7 -> 1.19.1`; verifique se foi corrigido na *patch* alvo antes de avançar).

> **Compatibilidade Cilium x Kubernetes:** Cilium 1.18 foi testado oficialmente até Kubernetes 1.34. Operar com K8s 1.35 e Cilium 1.18.7 funciona na prática, mas algumas features novas do K8s podem não estar disponíveis. Se sentir warnings ou regressões, é o sinal para avançar para Cilium 1.19.x.

---

## 5) Procedimento de upgrade (single-node server)

> Tudo abaixo deve correr **no nó RKE2**, com `sudo`.

### 5.1. Pré-checks rápidos

```bash
kubectl get nodes -o wide
kubectl get pods -A | grep -vE 'Running|Completed' || echo "todos pods OK"
sudo systemctl status rke2-server --no-pager | head -15
df -h /var/lib/rancher /var/lib/etcd 2>/dev/null
```

Resolva pendentes (ex.: pods em `CrashLoopBackOff`) **antes** de atualizar.

### 5.2. Snapshot extra do etcd (passo 2.1)

Execute aqui se ainda não o fez.

### 5.3. Reexecutar o instalador na versão alvo

Escolha **uma** das três formas:

```bash
# Opção A - canal stable (latest patch da minor estável)
curl -sfL https://get.rke2.io | sudo INSTALL_RKE2_CHANNEL=stable sh -

# Opção B - fixar minor 1.35 (latest patch dentro de 1.35)
curl -sfL https://get.rke2.io | sudo INSTALL_RKE2_CHANNEL=v1.35 sh -

# Opção C - versão exata
curl -sfL https://get.rke2.io | sudo INSTALL_RKE2_VERSION="v1.35.4+rke2r1" sh -
```

O *script* descarrega o binário novo para `/usr/local/bin/rke2` (instalação tarball) ou troca o pacote (instalação RPM). **Não reinicia** o serviço sozinho.

> **Instalação RPM:** se instalou o RKE2 via RPM (não é o caso default deste repositório), use `sudo dnf upgrade rke2-server` (e `rke2-selinux` se o tiver ativo). O script de instalação acima também detecta e usa o gerenciador de pacotes.

### 5.4. Reiniciar o serviço

```bash
sudo systemctl restart rke2-server
```

Acompanhe o arranque:

```bash
sudo journalctl -u rke2-server -f --since "2 min ago"
```

Aguarde `Reconciling ETCDSnapshotFile resources complete` e o nó voltar a `Ready`.

---

## 6) Validação pós-upgrade

### 6.1. Plano de controlo

```bash
rke2 --version
kubectl get nodes -o wide
kubectl version --short

kubectl get pods -A | grep -vE 'Running|Completed' || echo "todos pods OK"
kubectl -n kube-system get pods -l k8s-app=cilium -o wide
kubectl -n kube-system get pods -l io.cilium/app=operator -o wide
```

Espera-se ver:

- O nó com `VERSION` na nova *minor* (ex.: `v1.35.4+rke2r1`).
- Cilium *agent* e *operator* em `Running`. **Restarts são esperados** logo após o upgrade.

### 6.2. Cilium Gateway API e Envoy embedded

> Este passo é específico do *stack* deste repositório (kpr + Gateway API) e cobre o cenário "Envoy sem listeners" descrito em `docs/fine-tuning/README.md` (secção 5).

```bash
kubectl get gateway -A
kubectl get httproute -A

sudo ss -ltnp | grep -E ':80 |:443 '

LB=$(kubectl get svc -n cilium cilium-gateway-public \
       -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl -vk --resolve um.dos.teus.dominios:443:$LB \
  https://um.dos.teus.dominios/ -m 10
```

Se o `ss` não listar `:80` ou `:443`, ou o `curl` der `Connection reset by peer`, force a reconciliação:

```bash
kubectl -n kube-system rollout restart deploy/cilium-operator
kubectl -n kube-system rollout status   deploy/cilium-operator --timeout=3m

kubectl -n kube-system rollout restart ds/cilium
kubectl -n kube-system rollout status   ds/cilium --timeout=5m
```

### 6.3. Snapshot do etcd na versão nova

Para ter um ponto de retorno **já no formato da nova versão**:

```bash
sudo rke2 etcd-snapshot save --name "post-upgrade-$(date +%Y%m%d-%H%M)"
```

### 6.4. Aplicações

```bash
kubectl get applications -n argocd
kubectl get certificates -A
kubectl get pvc -A
```

Espere o ArgoCD reconciliar. Em janela curta pode aparecer `Progressing` ou `OutOfSync` enquanto os controllers se restabelecem.

---

## 7) Rollback

> O *downgrade* binário do RKE2 não é suportado em geral, **mas** é possível restaurar o cluster a partir de um snapshot do etcd tirado **antes** do upgrade. Em cluster de um nó, é literalmente reinstalar a versão antiga e fazer `--cluster-reset --cluster-reset-restore-path=<snapshot>`.

### 7.1. Reinstalar a versão antiga

```bash
sudo systemctl stop rke2-server

curl -sfL https://get.rke2.io | sudo INSTALL_RKE2_VERSION="v1.34.7+rke2r1" sh -
```

### 7.2. Restaurar o snapshot pré-upgrade

```bash
sudo rke2 server \
  --cluster-reset \
  --cluster-reset-restore-path=/var/lib/rancher/rke2/server/db/snapshots/pre-upgrade-YYYYMMDD-HHMM
```

O processo termina sozinho ao concluir o restore. **Em seguida**, arranque o serviço normalmente:

```bash
sudo systemctl start rke2-server
```

### 7.3. Validar

Repita o passo 6.

> **Atenção:** o restore reverte **todo o estado do cluster** ao momento do snapshot. Quaisquer alterações de aplicação (deploys, ConfigMaps, Secrets) feitas depois do snapshot **perdem-se**. Use só em incidente real.

---

## 8) Notas específicas v1.34 -> v1.35

- **Kubernetes 1.35**: ler [`CHANGELOG-1.35.md`](https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.35.md) para *deprecations* e *urgent upgrade notes*.
- **Cilium chart**: o RKE2 1.35.x empacota Cilium 1.19.x. Como o `HelmChartConfig` deste repositório fixa `v1.18.7`, **o data plane mantém-se em 1.18.7** após o upgrade. Para mover para 1.19, ver passo 4 e o issue [cilium/cilium#44430](https://github.com/cilium/cilium/issues/44430).
- **Etcd**: o RKE2 1.35.x continua a usar `etcd v3.6` (mesma série da v1.34.x). Sem mudança de formato/binário esperada.
- **Gateway API**: as CRDs vêm com o chart de Cilium e seguem a versão fixada. Não há ação adicional desde que o `HelmChartConfig` se mantenha.

---

## 9) Cluster HA (3+ servers) — apenas referência

> O caso deste repositório é single-node, mas se evoluir para HA, o procedimento muda:
>
> 1. Atualize **um servidor de cada vez**, esperando todos os pods reconciliarem antes de avançar para o próximo.
> 2. Apenas depois de **todos os servers** estarem na nova versão, atualize os agents (também um a um).
> 3. Considere o operador `system-upgrade-controller` para [upgrades automatizados](https://docs.rke2.io/upgrades/automated). Em cluster de um nó este operador é desnecessário.
