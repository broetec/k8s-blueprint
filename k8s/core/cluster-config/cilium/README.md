## Cilium Gateway API – IP público

Este diretório contém a configuração do Cilium (Gateway API + Ingress) para o cluster RKE2.

O objetivo desta configuração é:

- **Gateway público (`public`)**: expor sites de clientes usando um IP dedicado.
- **Ingress Cilium**: continuar atendendo aplicações legadas via Ingress.

### 1. Pré‑requisitos no cluster

- Cluster **RKE2** com:
  - `cni: cilium` em `/etc/rancher/rke2/config.yaml`
  - `disable: rke2-ingress-nginx`, `rke2-traefik`, `rke2-traefik-crd`
- Cilium instalado via manifest do RKE2, com algo próximo de:

```yaml
apiVersion: helm.cattle.io/v1
kind: HelmChartConfig
metadata:
  name: rke2-cilium
  namespace: kube-system
spec:
  valuesContent: |
    operator:
      replicas: 1
    kubeProxyReplacement: partial
    ingressController:
      enabled: true
      default: true
      loadbalancerMode: shared
      service:
        labels:
          network: public
    gatewayAPI:
      enabled: true
      gatewayClass:
        # String obrigatória no schema Helm: "true" | "false" | "auto"
        create: "false"
      # Recomendado começar sem hostNetwork para evitar impacto no SSH:
      hostNetwork:
        enabled: false
```

> **Importante**: alterar `kubeProxyReplacement` ou `gatewayAPI.hostNetwork.enabled`
> pode derrubar conexões SSH ativas. Faça sempre em janela de manutenção e, se
> possível, com acesso de console (out‑of‑band) ao nó.

- CRDs do Gateway API instalados (antes do overlay Cilium):

```bash
kubectl apply --server-side -k k8s/core/cluster-config/gateway-api
```

### 2. Estrutura dos arquivos

- `base/gatewayclass.yaml`  
  Define o `GatewayClass` `cilium` (`controllerName: io.cilium/gateway-controller`). Com `gatewayAPI.gatewayClass.create: "false"` no HelmChartConfig, este ficheiro é a única fonte de verdade para esse recurso.

- `base/gateway-public.yaml`  
  Define o `Gateway` público (`name: public`) com:
  - `gatewayClassName: cilium`
  - `infrastructure.labels.network: public`
  - `spec.addresses[0].value: PLACEHOLDER` (substituído pelo overlay)

- `overlays/<overlay>/kustomization.yaml`  
  Usa o `base` e aplica patches de JSON6902 nos dois Gateways:

  - `gateway-public.yaml`: substitui o valor do primeiro endereço (`spec.addresses[0].value`)
    pelo **IP público** desejado.

### 3. Ajustando os IPs via Services (`io.cilium/lb-ipam-ips`)

Em vez de definir o IP diretamente no `Gateway`, os IPs são fixados nos `Service`
tipo `LoadBalancer` usando a anotação `io.cilium/lb-ipam-ips`.

- `base/gateway-public-svc.yaml`  
  Service do Gateway público:

  ```yaml
  apiVersion: v1
  kind: Service
  metadata:
    name: gateway-public
  spec:
    type: LoadBalancer
    selector:
      gateway.networking.k8s.io/gateway-name: public
    ports:
      - name: http
        port: 80
        targetPort: 80
      - name: https
        port: 443
        targetPort: 443
  ```

Os overlays aplicam os IPs desejados nesses Services:

- `overlays/<overlay>/gateway-public-svc.yaml`

  ```yaml
  - op: add
    path: /metadata/annotations/io.cilium~1lb-ipam-ips
    value: "10.20.30.40"  # IP público
  ```

  ```

Para alterar:

1. Edite os valores `value: "..."` em `gateway-public-svc.yaml` 
   dentro de `overlays/<overlay>` conforme os IPs que você quer usar (por exemplo
   `10.0.0.50`).
2. Garanta que esses IPs estejam roteáveis até o cluster (BGP, L2, IPAM do Cilium, etc.).
3. Ajuste o DNS:
   - Registros públicos apontando para o IP do `Service` público.

### 4. Aplicando as configurações com Kustomize (`k apply -k`)

Usando o overlay `broetec-core` (ajuste o nome do overlay se necessário), a
partir da raiz do repositório:

```bash
kubectl apply --server-side -k k8s/core/cluster-config/cilium/overlays/broetec-core
```

Para inspecionar o render antes de aplicar:

```bash
kustomize build k8s/core/cluster-config/overlays/broetec-core | less
```

No fluxo normal isso é feito pelo role `04_deploy_k8s` no bootstrap e, depois,
pela Application `cluster-config` do Argo CD.

Isso irá:

- Criar/atualizar os recursos `Gateway`:
  - `public`
- Aplicar os IPs definidos nos arquivos de overlay.

### 5. Como isso se integra com Cilium

- Cada `Gateway` (`public`) é provisionado pelo Cilium (`gatewayClassName: cilium`).
- O Cilium usa:
  - `spec.addresses[0].value` como IP desejado.
  - `spec.infrastructure.labels.network` para selecionar pools de IP ou regras
    de rede, conforme sua configuração de IPAM/rede.
- O Ingress Cilium continua ativo para aplicações legadas (via `ingressController.enabled: true`).

### 6. Ordem sugerida de mudanças (sem perder SSH)

1. Configurar/ajustar o `rke2-cilium-config.yaml` conforme o trecho da seção 1, **sem** `hostNetwork.enabled: true` inicialmente.
2. Confirmar que o cluster está saudável:
   - `kubectl -n kube-system get pods -l k8s-app=cilium`
   - `kubectl -n kube-system get pods -l app.kubernetes.io/name=cilium-operator`
3. Instalar os CRDs do Gateway API (se ainda não instalados).
4. Ajustar os IPs nos overlays `gateway-public.yaml`
5. Aplicar o overlay:

   ```bash
   kubectl apply -k overlays/<overlay>
   ```

6. Verificar:
   - `kubectl get gateway -A`
   - `kubectl describe gateway public -n cilium`
7. Validar o acesso:
   - Testar sites de clientes via IP/nome público.

Se estiver tudo funcional e você quiser avançar para `kubeProxyReplacement: true`
ou habilitar `gatewayAPI.hostNetwork.enabled: true`, faça isso em:

- Janela de manutenção.
- Com acesso de console alternativo caso o SSH caia.

