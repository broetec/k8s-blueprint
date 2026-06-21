# PriorityClasses

Classes de prioridade do cluster para ordenar a evicção e o agendamento de pods sob pressão de recursos.

## Classes disponíveis

| Classe | Valor | Uso |
|--------|-------|-----|
| `pc-0-infra-core` | 1000000 | Rede, DNS e Storage (ex.: ingress-nginx) |
| `pc-1-operators` | 900000 | Operators (Percona PostgreSQL, MongoDB, etc.) |
| `pc-2-secrets-certs` | 800000 | Secrets e certificados (Sealed Secrets, External Secrets, Cert-Manager) |
| `pc-3-registry-harbor` | 700000 | Registry (Harbor) |
| `pc-4-databases` | 600000 | Instâncias de banco (MongoDB, PostgreSQL criados pelos operators) |
| `pc-5-management-auth` | 500000 | Gestão e auth (ArgoCD, Keycloak, etc.) |
| `pc-6-apps-priority` | 400000 | Aplicações com prioridade |
| `pc-7-apps-idle` | 300000 | Aplicações idle |
| `pc-8-background-jobs` | 200000 | Jobs em background |

## Onde está aplicado neste repo

As priorityClasses estão aplicadas **na pasta base** de cada componente (exceto Harbor e External Secrets), para que todos os overlays herdem o mesmo comportamento.

- **pc-0-infra-core**: `ingress-nginx/base/versions/1.13.3/` (patch `deployment-priorityclass.yaml`).
- **pc-1-operators**: `mongodb/operator/base/` e `postgres/operator/base/` (patch `deployment-priorityclass.yaml` em cada um).
- **pc-2-secrets-certs**: `sealed-secrets/base/`, `cert-manager/base/` (patch em cada) e `external-secrets-operator/base/` (patches inline no kustomization).
- **pc-3-registry-harbor**: Harbor via `values.yaml` em cada overlay (storage). Depende do chart Helm suportar `priorityClassName` nos values.
- **pc-5-management-auth**: `argocd/base/` (patches inline no kustomization para os 6 workloads).

## pc-4-databases (instâncias de banco)

As instâncias de MongoDB e PostgreSQL são criadas pelos operators a partir dos CRs. Para usar `pc-4-databases` nos pods das instâncias, configure no CR quando o operador permitir (ex.: `replsets[].template.spec.priorityClassName` no PerconaServerMongoDB ou equivalente no PerconaPG).

## Aplicações (pc-6, pc-7, pc-8)

As classes `pc-6-apps-priority`, `pc-7-apps-idle` e `pc-8-background-jobs` devem ser usadas nos manifests ou Helm values das aplicações de negócio, fora deste repositório de bootstrap.
