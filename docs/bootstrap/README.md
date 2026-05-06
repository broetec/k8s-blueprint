# k8s-core

Guia para preparar uma VM Rocky Linux e fazer o bootstrap de um cluster Kubernetes (RKE2) utilizando este repositório.

---

## Parte 1 - Preparar a VM Rocky Linux

> **Objetivo:** deixar o sistema operacional pronto (rede, SSH, swap, kernel, VPN etc.) para receber o RKE2.


### 1.0. Atualização do sistema e instalação de ferramentas básicas
```bash
sudo dnf update -y
sudo dnf install curl tar nano iptables iptables-nft net-tools epel-release wireguard-tools git zsh openssl htop -y
```


### 1.1. Desabilitar o firewall

Evita conflitos severos de rede, permitindo que o Kubernetes gerencie suas próprias regras de *iptables*.
```bash
sudo systemctl disable --now firewalld
```

### 1.2. Configuração do NetworkManager

Instrui o gerenciador de rede do Linux a ignorar as interfaces virtuais criadas pelo CNI do cluster, evitando quedas de conexão nos pods.
```bash
cat <<'EOF' | sudo tee /etc/NetworkManager/conf.d/rke2-cni.conf
[keyfile]
unmanaged-devices=interface-name:cilium*;interface-name:lxc*;interface-name:cali*;interface-name:flannel*
EOF

sudo systemctl reload NetworkManager
```


### 1.3. Configurar WireGuard
```bash
sudo nano /etc/wireguard/vfxdev.conf
```
Coloque o conteúdo das credenciais de VPN neste arquivo.
```bash
sudo systemctl enable --now wg-quick@vfxdev
sudo reboot
```

### 1.4. Desativação permanente do swap

O Kubernetes exige que a paginação de memória (swap) esteja desativada para garantir a performance e a estabilidade do `kubelet`.
```bash
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab
```

### 1.5. Habilitação do roteamento de IP (IP forwarding)

Permite que o kernel do Linux atue como um roteador, o que é obrigatório para que os pacotes de rede transitem entre os pods e os nós.
```bash
cat <<EOF | sudo tee /etc/sysctl.d/90-rke2.conf
net.ipv4.ip_forward = 1
EOF

sudo sysctl --system
```

### 1.6. Limites do inotify

Aumenta os limites de *watches* e de instâncias do inotify no kernel. Valores baixos costumam causar erros ao monitorizar muitos ficheiros (por exemplo ferramentas de desenvolvimento, IDEs ou componentes que observam o sistema de ficheiros).

```bash
cat <<EOF | sudo tee /etc/sysctl.d/90-inotify.conf
fs.inotify.max_user_watches = 1048576
fs.inotify.max_user_instances = 1024
EOF

sudo sysctl --system
```

### 1.7. Configurar Oh My Zsh
```bash
chsh -s /usr/bin/zsh
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
git clone https://github.com/zsh-users/zsh-autosuggestions ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/plugins/zsh-autosuggestions
sed -i 's/^#\?\s*HIST_STAMPS=.*/HIST_STAMPS="yyyy-mm-dd"/' ~/.zshrc
sed -i -E 's/^plugins=\([^)]*\)/plugins=(git zsh-autosuggestions)/' ~/.zshrc
```

### 1.8. Configurar chave SSH
```bash
mkdir .ssh
chmod 700 .ssh
touch .ssh/authorized_keys
chmod 600 .ssh/authorized_keys
nano .ssh/authorized_keys
```
Adicione sua chave SSH neste arquivo.

Configurar autenticação SSH
```bash
cat <<'EOF' | sudo tee /etc/ssh/sshd_config.d/50-cloud-init.conf > /dev/null
PasswordAuthentication no
PubkeyAuthentication yes
EOF
```

Após alterar o arquivo de configuração do SSH, reinicie o serviço para aplicar as mudanças:
```bash
sudo systemctl restart sshd
```


### 1.9. Ativação do QEMU Guest Agent (para instalação Proxmox)
```bash
sudo dnf install qemu-guest-agent -y
sudo systemctl enable --now qemu-guest-agent
```
> **Aviso Proxmox:** Lembre-se de ir na interface web do Proxmox > Sua VM > **Options** > **QEMU Guest Agent** e marcar como **Enabled**. Depois, reinicie a VM pelo painel para aplicar.


### 1.10. Instalar o Zabbix Agent 2 (opcional)

O **Zabbix Agent 2** (`zabbix-agent2`) corre no nó e envia métricas ao servidor ou *proxy* Zabbix (*active checks*), ou responde a pedidos do servidor (*passive checks*, porta **10050/tcp**). Neste guia o *firewall* local está desligado (passo 1.1); se voltar a restringir tráfego, abra a porta conforme a sua política.

**Repositório:** o caminho publicado para **Rocky Linux** na linha **7.4** segue o padrão  
`https://repo.zabbix.com/zabbix/7.4/stable/rocky/<N>/x86_64/`  
onde `<N>` é o major da distro (`10` para Rocky 10, `9` para Rocky 9, …). Isto difere do layout antigo `.../zabbix/7.0/rhel/10/...` usado noutras séries; confirme sempre o diretório no [repositório oficial](https://repo.zabbix.com/zabbix/) ou no [instalador](https://www.zabbix.com/download_installer) para a sua versão exata do servidor.

**Recomendado:** definir o repositório e instalar o pacote (facilita dependências e atualizações):

```bash
ZABBIX_MINOR=7.4
ROCKY_VER=$(rpm -E '%{rhel}')

sudo rpm -Uvh https://repo.zabbix.com/zabbix/${ZABBIX_MINOR}/release/rocky/${ROCKY_VER}/noarch/zabbix-release-latest-${ZABBIX_MINOR}.el${ROCKY_VER}.noarch.rpm

sudo dnf install zabbix-agent2 -y
```

**Configuração:** edite o ficheiro principal do agente e ajuste o endereço do servidor (ou *proxy*), o nome do host no Zabbix e, se usar *passive checks*, quem pode ligar ao agente.

```bash
sudo nano /etc/zabbix/zabbix_agent2.conf
```

Valores típicos (substitua pelos da sua instalação):

- `Server=` — IPs ou hostnames do **Zabbix Server**/*proxy* autorizados a pedidos *passive* (separados por vírgula).
- `ServerActive=` — destino para *active checks* (normalmente o mesmo servidor ou *proxy*, porta **10051** por omissão; pode usar `IP:porta`).
- `Hostname=` — **tem de coincidir** com o nome do host criado no frontend Zabbix.

Inicie e habilite o serviço:

```bash
sudo systemctl enable --now zabbix-agent2
sudo systemctl status zabbix-agent2
```


## Parte 2 - Instalação do Kubernetes (RKE2)

> **Objetivo:** instalar e configurar o RKE2 (server único) com Cilium e Gateway API.


### 2.0. Instalar Helm
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

### 2.1. Criar o diretório de configuração
```bash
sudo mkdir -p /etc/rancher/rke2/
```

### 2.2. Criar o arquivo `config.yaml`
Referência: https://docs.rke2.io/reference/server_config
```bash
cat <<EOF | sudo tee /etc/rancher/rke2/config.yaml
write-kubeconfig-mode: "0644"
cni: cilium
disable-kube-proxy: true
node-name: "PLACEHOLDER"
tls-san:
  - "PLACEHOLDER"                 # DNS do apiserver que você usa no kubeconfig (ex.: "vpndev.k8s0.viaflex.com.br" / seu FQDN)
  - "PLACEHOLDER"                 # IP/VIP (LAN) pelo qual você acessa o apiserver (ex.: IP fixo do nó em cluster 1 nó, ou VIP/LB em HA)
  - "PLACEHOLDER"                 # IP (VPN) somente se você acessa o apiserver via VPN (ex.: WireGuard) e esse IP aparece no endpoint
node-ip: "PLACEHOLDER"            # IP “interno” do nó para tráfego entre nós; prefira o IP da LAN/rede do cluster
advertise-address: "PLACEHOLDER"  # normalmente igual ao node-ip (1 nó). Em HA, tende a ser o IP da interface que fala com outros nós/etcd
secrets-encryption: true
etcd-snapshot-schedule-cron: "0 2,8,14,20 * * *" # Evita a janela de 00:00, quando muitos hosts/VPS executam backups e aumentam a latência do disco.
etcd-snapshot-retention: 5
etcd-snapshot-compress: false # Snapshots pequenos: desativar compressão reduz CPU/latência e diminui risco de timeout no etcd em nós mais lentos.

disable:
  - rke2-ingress-nginx

# Descomente em VPS com recursos compartilhados (vizinhos no host): CPU/disco/rede podem
# variar e aumentar a latência do etcd; heartbeat/election mais tolerantes evitam eleições desnecessárias.
# Valores 500/5000 são um meio-termo; 1000/10000 são para VPS com I/O muito instável.
# Os demais argumentos mantêm a base de dados enxuta e evitam OOM quando o etcd cresce.
# etcd-arg:
#   - "heartbeat-interval=1000"
#   - "election-timeout=10000"
#   - "quota-backend-bytes=8589934592"      # 8 GiB - evita "mvcc: database space exceeded"
#   - "auto-compaction-mode=periodic"
#   - "auto-compaction-retention=1h"        # compacta de hora a hora -> menos fsync
#   - "snapshot-count=10000"
#   - "max-request-bytes=1572864"

# Em VPS o etcd pode ficar lento esporadicamente. Estas tolerâncias evitam que o
# kube-apiserver derrube conexões, o controller-manager marque o nó como NotReady
# e dispare evictions em cascata (que geram ainda mais carga de disco).
# kube-apiserver-arg:
#   - "default-not-ready-toleration-seconds=300"
#   - "default-unreachable-toleration-seconds=300"
#   - "request-timeout=2m"
# kube-controller-manager-arg:
#   - "node-monitor-period=10s"
#   - "node-monitor-grace-period=120s"
# kubelet-arg:
#   - "node-status-update-frequency=20s"

# Snapshots remotos do etcd (sobreviver à perda total do disco local).
# Funciona com qualquer S3-compatível: AWS S3, Backblaze B2, Cloudflare R2, Wasabi, MinIO.
# Restauro em DR: rke2 server --cluster-reset --cluster-reset-restore-path=<arquivo>
# etcd-s3: true
# etcd-s3-endpoint: "s3.us-east-005.backblazeb2.com"
# etcd-s3-bucket: "PLACEHOLDER"
# etcd-s3-region: "us-east-005"
# etcd-s3-access-key: "PLACEHOLDER"
# etcd-s3-secret-key: "PLACEHOLDER"
# etcd-s3-folder: "PLACEHOLDER"             # ex.: nome do cluster

# control-plane-resource-requests:
#   - kube-apiserver=cpu=250m,memory=512Mi
#   - etcd=cpu=500m,memory=1Gi
#   - kube-controller-manager=cpu=200m,memory=256Mi
#   - kube-scheduler=cpu=100m,memory=128Mi

# control-plane-resource-limits:
#   - kube-apiserver=cpu=1000m,memory=1Gi
#   - etcd=cpu=1000m,memory=2Gi
#   - kube-controller-manager=cpu=500m,memory=512Mi
#   - kube-scheduler=cpu=300m,memory=256Mi
EOF
```

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

> **Importante:** Este manifest deve existir **antes** de subir o RKE2 (antes do `systemctl enable --now rke2-server`). Se o cluster já estiver rodando, altere o arquivo e reinicie o serviço: `sudo systemctl restart rke2-server.service` (ou aplique o HelmChartConfig via `kubectl apply` e force um upgrade do release: `helm upgrade -n kube-system rke2-cilium ...` com os mesmos values).


### 2.4. Baixar e instalar o RKE2
```bash
curl -sfL https://get.rke2.io | sudo sh -
```

### 2.5. Iniciar o cluster
```bash
sudo systemctl enable --now rke2-server.service
```

### 2.6. Configurar o acesso do usuário

Copia o kubeconfig para o utilizador, adiciona `kubectl`/`helm` ao PATH e ao *shell*, e define aliases usados no resto deste guia.

Para trocar facilmente o *namespace* ativo, use o plugin [`kubens`](https://github.com/ahmetb/kubectx) (parte do projeto `kubectx/kubens`): exemplo `kubens kube-system`.

```bash
mkdir -p ~/.kube

cp /etc/rancher/rke2/rke2.yaml ~/.kube/config

# kubectx/kubens (trocar contextos e namespace no kubectl)
if [ ! -d ~/.kubectx ]; then
  git clone https://github.com/ahmetb/kubectx.git ~/.kubectx
fi
echo 'export PATH=~/.kubectx:$PATH' >> ~/.zshrc

# Completion para zsh (oh-my-zsh)
if [ -d "$HOME/.oh-my-zsh" ]; then
  mkdir -p "$HOME/.oh-my-zsh/custom/completions"
  ln -sf "$HOME/.kubectx/completion/_kubens.zsh" "$HOME/.oh-my-zsh/custom/completions/_kubens.zsh"
  ln -sf "$HOME/.kubectx/completion/_kubectx.zsh" "$HOME/.oh-my-zsh/custom/completions/_kubectx.zsh"
  echo 'fpath=($HOME/.oh-my-zsh/custom/completions $fpath)' >> ~/.zshrc
  autoload -U compinit && compinit
fi

echo 'export PATH=$PATH:/var/lib/rancher/rke2/bin' >> ~/.zshrc
echo 'export KUBECONFIG=~/.kube/config' >> ~/.zshrc
echo 'source <(kubectl completion zsh)' >> ~/.zshrc
echo 'source <(helm completion zsh)' >> ~/.zshrc
echo "alias k='kubectl'" >> ~/.zshrc
echo "complete -F __start_kubectl k" >> ~/.zshrc
echo "alias kns='kubens'" >> ~/.zshrc
echo "alias kctx='kubectx'" >> ~/.zshrc
source ~/.zshrc
```

### 2.7. (Opcional) Limpar pods em estado `Completed`
```bash
k delete pod --field-selector=status.phase=Succeeded -A
```

### 2.8 Configuração inicial: clonar o repositório via Deploy Key (GitHub)

> Objetivo: permitir a clonagem do repositório `k8s-core` sem usar credenciais pessoais no GitHub (requer que o repositório seja privado).
>
> Pré-requisitos:
> 1. Acesso ao GitHub para adicionar a *deploy key* no repositório.
> 2. Ter o repositório (ou organização) configurado para aceitar essa chave.

#### 2.8.1 (Recomendado) Evitar prompts de host desconhecido
```bash
ssh-keyscan -H github.com >> ~/.ssh/known_hosts
```

#### 2.8.2 Gerar o par de chaves SSH (deploy key)
```bash
ssh-keygen -t ed25519 -C "$(hostname -f 2>/dev/null || hostname)" -f ~/.ssh/k8s-core -N ""

echo
echo "Public key (adicione no GitHub):"
cat ~/.ssh/k8s-core.pub
```

#### 2.8.3 Adicionar a chave como Deploy Key no GitHub
1. No GitHub, abra o repositório `k8s-core`.
2. Vá em `Settings` -> `Deploy keys`.
3. Clique em `Add deploy key`.
4. Cole o conteúdo de `~/.ssh/k8s-core.pub` (public key).
5. Em geral, marque como `Read-only` (ou desmarque `Allow write`), a menos que você realmente precise fazer `push` a partir desse ambiente.

#### 2.8.4 Clonar o repositório usando a deploy key
```bash
eval $(ssh-agent -s)
ssh-add ~/.ssh/k8s-core

git clone git@github.com:Viaflex-H-S/k8s-core.git ~/k8s-core
cd ~/k8s-core
```

Depois da clonagem, execute o restante do guia a partir do diretório `k8s-core` (por exemplo, no passo `3.0` do guia, você vai aplicar `cluster-config/...`).


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
