# Fine tuning de host para RKE2 em VPS

Este guia reúne ajustes de **kernel**, **systemd** e operações de **I/O** para melhorar a resiliência do RKE2 (especialmente etcd) em VPS com disco partilhado/thin-provisioned.

Use em conjunto com o guia principal em `README.md`.

---

## 1) Timers de manutenção que provocam picos de I/O

Em VPS com armazenamento partilhado/thin-provisioned (ex.: Hostinger, OVH, Hetzner Cloud) o `fstrim.timer` semanal pode bloquear o filesystem o suficiente para o **etcd** sofrer *timeouts* de `fsync` e a unit do `rke2-server` desistir de reiniciar (ver `StartLimitBurst` na unit padrão). Em casos extremos o cluster só recupera com *reboot* da máquina.

Outros *timers* costumam concentrar-se na janela das 00:00-04:00 e amplificam o problema:

| Timer | Para que serve | Recomendação em nó RKE2 |
|---|---|---|
| `fstrim.timer` | TRIM semanal do FS | **Desativar** em VPS (o hipervisor já gere) |
| `mlocate-updatedb.timer` | Indexa todo o FS para o `locate` | **Desativar** (não faz sentido em servidor) |
| `dnf-makecache.timer` | Refresca metadados do dnf | Desativar; corre no `dnf update` manual |
| `logrotate.timer` | Rotação de logs | Manter, mas rever tamanho dos logs do containerd |

Inspecionar e desativar:

```bash
# Listar tudo e ver o que corre nas próximas horas
systemctl list-timers --all

# Desativar os mais barulhentos
sudo systemctl disable --now fstrim.timer
sudo systemctl disable --now mlocate-updatedb.timer
sudo systemctl disable --now dnf-makecache.timer
```

Se preferir manter o `fstrim` mas em horário ocioso (ex.: domingo às 04:00):

```bash
sudo systemctl edit fstrim.timer
# [Timer]
# OnCalendar=
# OnCalendar=Sun 04:00
```

> **Nota:** o backup automático do *cloud provider* (snapshot do disco da VM) costuma cair perto da meia-noite e **não** é desativável pelo utilizador. O melhor mitigante é reduzir tudo o resto e tornar o RKE2 tolerante (kernel + systemd + watchdog).

---

## 2) Tuning de kernel para discos lentos

Estas opções reduzem o impacto de picos de I/O no etcd e fazem o nó auto-recuperar em caso de *hang* prolongado.

```bash
cat <<EOF | sudo tee /etc/sysctl.d/95-rke2-disk.conf
# Fluxo de páginas sujas: escreve mais cedo e em pedaços menores,
# evitando "rajadas" de fsync que travam o etcd em discos lentos.
vm.dirty_background_ratio = 5
vm.dirty_ratio = 10
vm.dirty_expire_centisecs = 1000
vm.dirty_writeback_centisecs = 500

# Já temos swap-off no guia principal, mas reforça a intenção.
vm.swappiness = 1

# Auto-recuperação: se o kernel entrar em panic ou OOM, reinicia em 30s.
# Última linha de defesa - em conjunto com Restart=always do rke2-server.
kernel.panic = 30
kernel.panic_on_oom = 1

# Detecta tasks bloqueadas por mais de 10 min (default 120s gera spam em VPS lenta)
kernel.hung_task_timeout_secs = 600
EOF

sudo sysctl --system
```

**Mount options para a partição do `/var/lib/rancher`:** adicionar `noatime,nodiratime` reduz writes desnecessários em cada leitura. Editar `/etc/fstab` (a entrada exata depende do *layout* da máquina - em Rocky com LVM costuma ser `/` ou um volume separado):

```fstab
# Exemplo (ajuste o device/UUID e os opts existentes):
UUID=...   /   xfs   defaults,noatime,nodiratime   0 0
```

Aplicar sem reboot:

```bash
sudo mount -o remount,noatime,nodiratime /
```

> **Boas práticas extra:** se a VPS permitir, montar `/var/lib/rancher` num volume dedicado dá ao etcd um *queue* de I/O isolado dos restantes processos do nó.

---

## 3) Diagnóstico de performance do etcd

O upstream considera saudável `wal_fsync_duration_seconds` p99 < 25 ms e `backend_commit_duration_seconds` p99 < 25 ms. Em VPS é normal ficar acima; se passar consistentemente de 100 ms, o disco é o gargalo.

```bash
sudo /var/lib/rancher/rke2/bin/etcdctl \
  --cacert /var/lib/rancher/rke2/server/tls/etcd/server-ca.crt \
  --cert   /var/lib/rancher/rke2/server/tls/etcd/server-client.crt \
  --key    /var/lib/rancher/rke2/server/tls/etcd/server-client.key \
  --endpoints https://127.0.0.1:2379 check perf
```

---

## 4) Hardening do `rke2-server.service` (prioridade + auto-restart)

No RKE2, o **etcd** corre no mesmo processo/serviço que o resto do plano de controlo (`rke2-server`). Um *override* do systemd serve para duas coisas:

1. **Prioridade de CPU/I/O** - ajuda a estabilidade da API e das eleições do etcd quando o nó tem disco ou CPU disputados.
2. **Auto-restart resiliente** - a unit padrão tem `Restart=always`, mas com `StartLimitBurst=5` em janela curta. Se o disco fica lento por 1-2 min (ex.: backup do *cloud provider*, `fstrim`), o systemd entra em `failed` e **só recupera com reboot manual**. As opções abaixo eliminam esse limite e dão tempo ao etcd para abrir o WAL.

Crie ou edite o *drop-in* do serviço:

```bash
sudo systemctl edit rke2-server.service
```

No editor, acrescente:

```ini
[Service]
# Prioridade de CPU acima do default (0). Valores mais negativos = mais prioridade.
Nice=-10
# Classe de I/O Best-Effort (2) com a maior prioridade dentro da classe (0).
IOSchedulingClass=2
IOSchedulingPriority=0

# Auto-restart agressivo - vital em VPS com I/O instável.
Restart=always
RestartSec=15s
# Etcd lento pode demorar a recuperar o WAL após picos de latência.
TimeoutStartSec=20min
TimeoutStopSec=2min

[Unit]
# Nunca desistir: tenta reiniciar indefinidamente até o disco voltar ao normal.
StartLimitIntervalSec=0
StartLimitBurst=0
```

Guarde e feche o ficheiro; depois recarregue o systemd e reinicie o RKE2:

```bash
sudo systemctl daemon-reload
sudo systemctl restart rke2-server.service
```

Para confirmar que o *drop-in* foi aplicado:

```bash
systemctl cat rke2-server.service | grep -E 'Nice|IOScheduling|Restart|Timeout|StartLimit'
```

> **Nota:** `Nice=-10` exige permissões adequadas; se o sistema recusar, teste `-5` ou confirme limites em `ulimit`/política do sistema.
>
> **Por que `StartLimitIntervalSec=0`?** Sem isto, depois de 5 falhas consecutivas o systemd marca a unit como `failed` e **deixa de tentar reiniciar** até intervenção manual. Em VPS é exatamente o cenário a evitar - quando o disco voltar ao normal o systemd tem de continuar a tentar.

---

## 5) (Opcional) Watchdog externo de saúde da API

Mesmo com `Restart=always`, há três cenários em que o `rke2-server` não recupera sozinho:

1. **API morta com processo vivo** - o `rke2-server` está a executar mas o etcd está preso em `fsync` ou o apiserver não responde a `/readyz`. O systemd não reinicia porque o processo principal nunca terminou.
2. **Containers órfãos a bloquear o restart** - depois de uma falha violenta, *containerd-shims* dos pods anteriores continuam a executar (vê-se no `journalctl` como `Unit process X (containerd-shim) remains running after unit stopped`). Esses shims:
   - Mantêm portas/sockets do plano de controlo ocupados (`:6443`, `:2379`, `:2380`, `:10250`).
   - Mantêm o WAL do etcd aberto, impedindo o recovery do `data-dir`.
   - Continuam a martelar o disco lento, criando um *deadlock* de I/O.

   O RKE2 instala um script oficial - **`/usr/local/bin/rke2-killall.sh`** - que mata todos os shims, desmonta os volumes do `kubelet`/CNI e apaga interfaces órfãs (`cni0`, `cilium_*`, etc.). **Não apaga** o `data-dir` (isso é o `rke2-uninstall.sh`), portanto é seguro em produção.
3. **Data plane do Cilium meio-programado** - mesmo depois de um `rke2-killall.sh` + `start` bem-sucedido, com `kubeProxyReplacement: true` e `gatewayAPI.enabled: true` (o setup deste guia) é comum o `cilium-agent` arrancar antes de o apiserver estar 100% pronto e ficar com o **Envoy embedded sem listeners** (logs `loading 0 listener(s)`). O nó volta a ficar `Ready`, os pods aparecem `Running`, mas:
   - `ss -ltnp` mostra apenas a `:6443`, sem `:80`/`:443`.
   - O Service `cilium-gateway-public/-vpn` mantém EXTERNAL-IP (placeholder do Cilium), mas qualquer `curl --resolve` ao IP do LB devolve `Connection reset by peer`.
   - Os logs do agent mostram `connect: connection refused 127.0.0.1:6443` ou `... is forbidden: ... cannot get resource "ciliumendpoints"` enquanto o apiserver/RBAC ainda não estabilizou.

   A correção é forçar a re-sincronização Cilium ↔ apiserver com `rollout restart deploy/cilium-operator` e `rollout restart ds/cilium`, depois de garantir que o apiserver responde a `/readyz`. Nos logs vê-se o agente novo a programar os listeners (`Adding new proxy port rules ... cilium-gateway-public/listener proxyPort=...` e `[lds: add/update listener 'cilium/cilium-gateway-public/listener']`) e o tráfego volta sem `reboot`.

O watchdog abaixo implementa **escalada gradual** com base num *strike counter* em `/run`, e em **todos** os caminhos que reinstalam o RKE2 corre um passo de **reconciliação do data plane** (Cilium operator + agent), que cobre o cenário 3.

| Estado | Ação |
|---|---|
| API responde | Reset do contador. |
| API morta, *strike* 1 | `systemctl restart rke2-server.service` -> `wait_for_api` -> `reconcile_dataplane`. |
| API morta, *strike* >= 2 (>= 5 min consecutivos) | `stop` -> `rke2-killall.sh` -> `start` -> `wait_for_api` -> `reconcile_dataplane`. |
| `rke2-server` inativo | `systemctl start rke2-server.service` (o próximo ciclo do timer encarrega-se do reconcile). |

> **Nota sobre dependências:** o `reconcile_dataplane` inclui um `conntrack -F` opcional para descartar entradas *stale* depois do killall. O pacote `conntrack-tools` não está instalado por defeito em Rocky Linux; instale-o com `sudo dnf install -y conntrack-tools` se quiser ativar este passo (o script é tolerante à ausência).

```bash
sudo tee /usr/local/sbin/rke2-healthcheck.sh >/dev/null <<'EOF'
#!/usr/bin/env bash
set -u
KCFG=/etc/rancher/rke2/rke2.yaml
KUBECTL=/var/lib/rancher/rke2/bin/kubectl
KILLALL=/usr/local/bin/rke2-killall.sh
STATE=/run/rke2-healthcheck.strikes

api_ready() {
  timeout 30 "$KUBECTL" --kubeconfig="$KCFG" get --raw=/readyz >/dev/null 2>&1
}

# Espera que o apiserver responda a /readyz por até 10 min após um restart.
# Sem isto, o reconcile do data plane corre contra um apiserver indisponível.
wait_for_api() {
  local deadline=$((SECONDS + 600))
  while (( SECONDS < deadline )); do
    api_ready && return 0
    sleep 5
  done
  return 1
}

# Reconcilia o data plane do Cilium (kpr + Gateway API):
# - rollout do operator garante LB-IPAM e reaplicação de CRDs do Gateway.
# - rollout do agent reabre os listeners do Envoy embedded (cenário 3).
# - conntrack -F descarta entradas stale depois do killall (best-effort).
# É idempotente: se tudo já estiver bom, é apenas um restart pod-by-pod.
reconcile_dataplane() {
  logger -t rke2-healthcheck "reconciling Cilium data plane"

  "$KUBECTL" --kubeconfig="$KCFG" -n kube-system rollout restart deploy/cilium-operator || true
  "$KUBECTL" --kubeconfig="$KCFG" -n kube-system rollout status   deploy/cilium-operator --timeout=3m || true

  "$KUBECTL" --kubeconfig="$KCFG" -n kube-system rollout restart ds/cilium || true
  "$KUBECTL" --kubeconfig="$KCFG" -n kube-system rollout status   ds/cilium --timeout=5m || true

  command -v conntrack >/dev/null && conntrack -F >/dev/null 2>&1 || true

  "$KUBECTL" --kubeconfig="$KCFG" delete pod -A \
    --field-selector=status.phase=Failed --ignore-not-found >/dev/null 2>&1 || true
}

# Cenário 0: serviço inativo (failed / stopped) - só tenta start.
# O reconcile fica para o próximo ciclo, quando a API já estiver pronta.
if ! systemctl is-active --quiet rke2-server.service; then
  logger -t rke2-healthcheck "rke2-server inativo - a iniciar"
  systemctl start rke2-server.service || true
  exit 0
fi

# Cenário 1: API saudável - limpar o contador e sair.
if api_ready; then
  rm -f "$STATE"
  exit 0
fi

# Cenário 2/3/4: API doente - escalar conforme o número de falhas consecutivas.
strikes=$(cat "$STATE" 2>/dev/null || echo 0)
strikes=$((strikes + 1))
echo "$strikes" > "$STATE"

if [ "$strikes" -ge 2 ] && [ -x "$KILLALL" ]; then
  logger -t rke2-healthcheck "API morta há $strikes ciclos - killall + restart + reconcile"
  systemctl stop rke2-server.service || true
  "$KILLALL" || true
  systemctl start rke2-server.service || true
  if wait_for_api; then
    reconcile_dataplane
    rm -f "$STATE"
  else
    logger -t rke2-healthcheck "wait_for_api falhou apos killall - mantendo strike"
  fi
else
  logger -t rke2-healthcheck "API nao respondeu (strike $strikes) - restart simples + reconcile"
  systemctl restart rke2-server.service || true
  if wait_for_api; then
    reconcile_dataplane
  fi
fi
EOF
sudo chmod +x /usr/local/sbin/rke2-healthcheck.sh

sudo tee /etc/systemd/system/rke2-healthcheck.service >/dev/null <<'EOF'
[Unit]
Description=RKE2 API health check
After=rke2-server.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/rke2-healthcheck.sh
EOF

sudo tee /etc/systemd/system/rke2-healthcheck.timer >/dev/null <<'EOF'
[Unit]
Description=Run rke2-healthcheck every 5 minutes

[Timer]
OnBootSec=10min
OnUnitActiveSec=5min
Unit=rke2-healthcheck.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now rke2-healthcheck.timer
```

Verificar funcionamento:

```bash
systemctl list-timers rke2-healthcheck.timer
journalctl -t rke2-healthcheck -n 20
cat /run/rke2-healthcheck.strikes 2>/dev/null || echo "0 (saudável)"
```

**Quando precisar correr o `rke2-killall.sh` manualmente** (ex.: depois de um incidente em que reiniciaste a VM mas alguns shims continuaram pendurados):

```bash
sudo /usr/local/bin/rke2-killall.sh
sudo systemctl start rke2-server.service

# Aguardar /readyz e reabrir os listeners do Envoy embedded do Cilium.
# Sem este passo, num cluster com kubeProxyReplacement + Gateway API,
# o nó volta a Ready mas o tráfego externo (80/443) não chega aos pods.
until kubectl --kubeconfig=/etc/rancher/rke2/rke2.yaml get --raw=/readyz >/dev/null 2>&1; do
  sleep 5
done
kubectl -n kube-system rollout restart deploy/cilium-operator
kubectl -n kube-system rollout status   deploy/cilium-operator --timeout=3m
kubectl -n kube-system rollout restart ds/cilium
kubectl -n kube-system rollout status   ds/cilium --timeout=5m
```

Para confirmar que o data plane voltou:

```bash
sudo ss -ltnp | grep -E ':80 |:443 '   # deve listar cilium-agent
LB=$(kubectl get svc -n cilium cilium-gateway-public \
       -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl -vk --resolve um.dos.teus.dominios:443:$LB \
  https://um.dos.teus.dominios/ -m 10
```

> **Cuidado:** este watchdog reinicia o serviço inteiro do plano de controlo e o `rke2-killall.sh` derruba **todos** os pods do nó. Em cluster HA (3 servers) é mais conservador apontar o `--raw=/readyz` para o IP local e deixar a função de eleição cuidar do resto; em cluster de **um nó** (caso deste guia) é a rede de segurança que evita *downtime* prolongado e cobre os cenários "containers ainda em execução a bloquear o restart" e "Envoy embedded sem listeners" sem precisar de *reboot* manual.
