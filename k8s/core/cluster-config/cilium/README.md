# Cilium Gateway API – Gateway `public`

Este diretório contém os recursos de rede do cluster RKE2 que ficam no Git: a
`GatewayClass` do Cilium, o Gateway `public` e o LB-IPAM que dá a ele o IP da
VM.

Não há Ingress neste repo. O role 03 desliga todos os controladores de Ingress
que o RKE2 traz (`rke2-ingress-nginx`, `rke2-traefik`, `rke2-traefik-crd`) e o
Cilium não roda o `ingressController`. Aplicações são publicadas com
`HTTPRoute` apontando para o Gateway `public`.

## 1. Configuração do Cilium (role 03)

O Cilium é o CNI do RKE2 e é configurado antes do cluster subir, pelo
`HelmChartConfig` que o role 03 grava em
`/var/lib/rancher/rke2/server/manifests/rke2-cilium-config.yaml`. O template é
[`rke2-cilium-config.yaml.j2`](../../../../provisioning/roles/03_install_rke2/templates/rke2-cilium-config.yaml.j2);
com os valores padrão ele gera:

```yaml
apiVersion: helm.cattle.io/v1
kind: HelmChartConfig
metadata:
  name: rke2-cilium
  namespace: kube-system
spec:
  valuesContent: |-
    k8sServiceHost: "10.20.30.40"      # rke2_advertise_address (IP da VM)
    k8sServicePort: 6443
    operator:
      replicas: 1
      image:
        override: quay.io/cilium/operator-generic:v1.20.2
    image:
      repository: quay.io/cilium/cilium
      tag: v1.20.2
    kubeProxyReplacement: true
    gatewayAPI:
      enabled: true
      gatewayClass:
        create: "false"                # a GatewayClass vem de base/gatewayclass.yaml
```

| Variável (role 03) | Padrão | Efeito |
|--------------------|--------|--------|
| `rke2_cilium_version` | `v1.20.2` | Imagens do agente e do operator (a mesma versão que o RKE2 traz) |
| `rke2_cilium_operator_replicas` | `1` | Evita conflito de portas em cluster de um nó |
| `rke2_cilium_kube_proxy_replacement` | `true` | Cilium substitui o kube-proxy (`rke2_disable_kube_proxy: true`) |
| `rke2_cilium_gateway_api_enabled` | `true` | Controlador de Gateway API do Cilium |
| `rke2_disable` | `rke2-ingress-nginx`, `rke2-traefik`, `rke2-traefik-crd` | Nenhum Ingress embutido; o `rke2-traefik-crd` também conflitaria com os CRDs do Gateway API |

> **Importante**: alterar `kubeProxyReplacement` ou ligar
> `gatewayAPI.hostNetwork.enabled` pode derrubar conexões SSH ativas. Faça em
> janela de manutenção e com acesso de console ao nó.

### CRDs do Gateway API

Os CRDs vêm de [`../gateway-api`](../gateway-api/kustomization.yaml): pacote
**v1.6.3, canal standard**, aplicado pelo role 04 antes deste diretório
(fora do Argo CD).

| Ponto | Detalhe |
|-------|---------|
| Versão mínima | O Cilium 1.20 exige Gateway API v1.6.1 ou mais nova (`TLSRoute` passou a `v1`) |
| Canal | Standard: desde a v1.6 já traz `ListenerSet`, `TCPRoute`, `UDPRoute` e `TLSRoute` em `v1`. O experimental acrescenta só os CRDs `gateway.networking.x-k8s.io` (`XBackend`, `XBackendTrafficPolicy`, `XMesh`) e campos experimentais (retry, CORS no `HTTPRoute`), que o repo não usa |
| `safe-upgrades` | O pacote instala a `ValidatingAdmissionPolicy` `safe-upgrades.gateway.networking.k8s.io`: recusa CRDs abaixo da v1.5 e a troca de standard para experimental (para isso, apague a policy antes). Experimental → standard é permitido |
| Troca de versão | Edite a URL em `../gateway-api/kustomization.yaml` e rode `make deploy-k8s`. O role reinicia o `cilium-operator` quando a versão ou o canal do pacote mudam, porque ele só habilita os tipos cujos CRDs existiam quando subiu |
| Cluster criado com o experimental | `make deploy-k8s` passa os CRDs para o standard e reinicia o operator, mas não fica igual a uma instalação nova: os CRDs `x-k8s.io` continuam no cluster e `TLSRoute`/`TCPRoute`/`UDPRoute` seguem servindo as versões `v1alpha*` antigas. Nada no repo usa essas versões. Para ficar limpo, recrie a VM (`make destroy && make up`) ou apague os CRDs `x-k8s.io` com `kubectl get crd -o name \| grep x-k8s.io \| xargs kubectl delete` |

## 2. Arquivos

`base/` (comum a todos os overlays, namespace `cilium`):

| Arquivo | Recurso |
|---------|---------|
| `namespace.yaml` | Namespace `cilium` |
| `gatewayclass.yaml` | `GatewayClass` `cilium` (`io.cilium/gateway-controller`); única fonte desse recurso, já que o chart não a cria |
| `gateway-public.yaml` | `Gateway` `public`: listeners HTTP (80) e HTTPS (443) com o certificado `public-tls-secret` emitido pelo cert-manager |
| `lb-pool.yaml` | `CiliumLoadBalancerIPPool` `lb-pool` |
| `policy.yaml` | `CiliumL2AnnouncementPolicy` `l2-policy` |

`overlays/<id>/` (patches JSON6902 sobre a base):

| Arquivo | O que ajusta | Variável do `_template` |
|---------|--------------|------------------------|
| `gateway-public.yaml` | IP do Gateway (`spec.addresses[0]`) e hostname do listener HTTPS (`*.<domínio>`) | `vm_ip`, `apps_domain` |
| `lb-pool.yaml` | Bloco do pool: o IP da VM em `/32` | `vm_ip` |
| `policy.yaml` | Interface de rede da VM | `iface` |
| `_tls-issuer.yaml` | Annotation `cert-manager.io/cluster-issuer` do Gateway | `tls_issuer` |

O role 04 reescreve o `_tls-issuer.yaml` na cópia enviada à VM com o emissor
efetivo: o `tls_issuer` do inventário (ou `TLS_ISSUER=` no make), trocado por
`selfsigned` quando é um `letsencrypt-*` e falta o token do Cloudflare.

## 3. Como o Gateway recebe o IP

1. O Gateway pede o IP da VM em `spec.addresses`.
2. O Cilium cria o Service `LoadBalancer` do Gateway com os labels e annotations
   de `spec.infrastructure` (`network: public`, `lb-ipam-sharing-key`).
3. O LB-IPAM atribui o IP a partir do `lb-pool`, que contém só esse endereço.

Como o IP do Gateway é o próprio IP do nó, o tráfego chega sem anúncio ARP
extra. A `CiliumL2AnnouncementPolicy` só tem efeito com
`l2announcements.enabled: true` no Cilium, que o role 03 não liga; ela fica no
repo para um IP de Gateway diferente do IP do nó.

## 4. Como alterar e aplicar

Os overlays `broetec-*` e os locais são gerados a partir de
`overlays/_template/`. Para mudar IP, domínio ou interface, altere o `k8s:` do
[`manifest.yml`](../../../../provisioning/inventory/manifest.yml) (ou o
`manifest.local.yml`) ou o template, e renderize:

```bash
uv run k8s-blueprint overlay render broetec-core
kustomize build k8s/core/cluster-config/cilium/overlays/broetec-core   # inspecionar
make k8s-push OVERLAY=broetec-core                                    # publicar
```

No bootstrap o role `04_deploy_k8s` aplica `k8s/core/cluster-config/overlays/<id>`
(Cilium + PriorityClasses); depois a Application `cluster-config` do Argo CD
mantém esses recursos.

## 5. Verificação

```bash
kubectl get gatewayclass cilium
kubectl -n cilium get gateway public          # PROGRAMMED=True e o IP da VM
kubectl -n cilium describe gateway public
kubectl get ciliumloadbalancerippool lb-pool
kubectl get httproute -A                      # rotas presas ao Gateway public
```

Se o Cilium não aplicar mudanças no Gateway, reinicie o operator:

```bash
kubectl rollout restart deployment -n kube-system cilium-operator
```
 