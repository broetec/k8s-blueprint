# k8s-blueprint — documentação

Laboratório Broetec para estudar Ansible, KVM/libvirt e Kubernetes.

```{toctree}
:caption: Introdução
:maxdepth: 1

../README
structure
```

```{toctree}
:caption: Provisionamento Ansible
:maxdepth: 1

../provisioning/README
../provisioning/inventory/README
../provisioning/collections/README
../provisioning/connection_plugins/README
../provisioning/templates/README
```

```{toctree}
:caption: Roles Ansible
:maxdepth: 1

../provisioning/roles/00_install_kvm/README
../provisioning/roles/01_create_vm/README
../provisioning/roles/02_prepare_vm/README
../provisioning/roles/03_install_k3s/README
../provisioning/roles/03_install_rke2/README
../provisioning/roles/04_deploy_k8s/README
```

```{toctree}
:caption: Kubernetes
:maxdepth: 1

../k8s/README
bootstrap/README
fine-tuning/README
upgrade/README
```

```{toctree}
:caption: Ferramentas
:maxdepth: 1

../make/README
../app/inventory/README
../env/README
../lab/README
```
