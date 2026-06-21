# Sealed Secrets

O controller é instalado via **Helm** antes do deploy do ArgoCD. Ver o [README principal](../README.md) para o comando de instalação.

- **base/values.yaml**: template com os default values do chart (referência).
- **overlays/storage/values.yaml**: values usados no deploy (bootstrap e ArgoCD).

## Key Management

This document outlines the procedures for backing up and restoring the master key used by the Sealed Secrets controller. This key is crucial, as it's used to encrypt your secrets. Losing this key means you won't be able to decrypt any secrets sealed with it.

## Backing Up the Master Key

The Sealed Secrets controller generates a public/private key pair upon installation and stores it as a Kubernetes Secret in the same namespace where the controller is running (commonly `kube-system`, but verify your installation).

To back up the key:

1.  Identify the namespace where your Sealed Secrets controller is running.
2.  Export the secret containing the **private and public key pair** to a YAML file using `kubectl`. This file contains the private key and should be kept secure.

    ```bash
    kubectl get secret -n sealed-secrets -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > master.key
    ```

    _(Replace `<namespace>` with the correct namespace)_

3.  **(Optional but Recommended) Export the public key separately.** This public key can be safely shared and is used by the `kubeseal` CLI to encrypt secrets without needing direct cluster access.

    ```bash
    # Fetch the public key from the running controller and save it
    kubectl get secret -n sealed-secrets -l sealedsecrets.bitnami.com/sealed-secrets-key=active \
    -o jsonpath="{.items[0].data['tls\.crt']}" | base64 -d > pub-cert.pem
    ```

    _(Replace `<namespace>` with the correct namespace. Ensure `kubeseal` is installed and `kubectl` is configured to access the cluster)_

4.  **Store the `master.key` file securely.** This file contains your private key and must be protected from unauthorized access. Treat it like any other sensitive credential. The `pub-sealed-secrets.pem` file can be stored less securely, for example, in your Git repository alongside your code, allowing others to seal secrets without cluster access.

## Restoring the Master Key

If you need to reinstall the Sealed Secrets controller (e.g., cluster migration, disaster recovery), you must restore the original master key _before_ applying any `SealedSecret` resources. Otherwise, the controller will generate a new key pair, and you won't be able to decrypt secrets sealed with the old key.

To restore the key:

1.  Ensure the Sealed Secrets controller is installed (or about to be installed) but hasn't necessarily created its default key yet.

2.  If the controller already started **without** restoring your backup, it will have created a **new** key as a Kubernetes `Secret` in the controller namespace. You must **delete that auto-generated key** before applying `master.key`; otherwise `kubectl apply` may merge/update incorrectly or the controller keeps using the wrong material.

    ```bash
    kubectl delete secret -n <namespace> -l sealedsecrets.bitnami.com/sealed-secrets-key
    ```

    _(Replace `<namespace>` with the namespace where Sealed Secrets runs, e.g. `sealed-secrets`.)_

3.  Apply the backed-up `master.key` file using `kubectl`:

    ```bash
    kubectl apply -f master.key
    ```

4.  If the controller was already running with a _different_ key, restart it so it reloads the restored key. Com o **Helm chart** usado neste repositório (Bitnami), o *Deployment* costuma chamar-se `sealed-secrets` e os pods **não** usam o label `name=sealed-secrets-controller` (isso é típico de manifests “vanilla” do projeto upstream).

    ```bash
    # Opção recomendada (reinicia o Deployment inteiro)
    kubectl rollout restart deployment/sealed-secrets -n <namespace>

    # Alternativa: apagar o pod pelos labels do chart
    kubectl delete pod -n <namespace> -l app.kubernetes.io/name=sealed-secrets
    ```

    _(Replace `<namespace>` com o namespace do controller, ex.: `sealed-secrets`.)_

Once the key is restored and the controller is using it, you can apply your `SealedSecret` resources, and they will be decrypted correctly.

## Troubleshooting: `SealedSecret` applied before restoring `master.key`

If a `SealedSecret` was applied before the original `master.key` was restored, the controller will already have created a **new** key `Secret` in the cluster. That key must be removed before the backup can take effect.

1.  Delete the auto-generated key `Secret` (same label used for backup):

    ```bash
    kubectl delete secret -n <namespace> -l sealedsecrets.bitnami.com/sealed-secrets-key
    ```

2.  Apply the backed-up `master.key`:

    ```bash
    kubectl apply -f master.key
    ```

3.  Restart the controller to force key reload:

    ```bash
    kubectl rollout restart deployment/sealed-secrets -n sealed-secrets
    # ou: kubectl delete pod -n sealed-secrets -l app.kubernetes.io/name=sealed-secrets
    ```

4.  Re-apply the affected `SealedSecret` resources (or re-sync via ArgoCD):

    ```bash
    kubectl apply -f <sealed-secret-file>.yaml
    ```

5.  Validate if the decrypted `Secret` was created:

    ```bash
    kubectl get secret -n <namespace>
    kubectl describe sealedsecret -n <namespace> <name>
    ```

If it still fails, check controller logs for `no key could decrypt secret` or similar errors. In this case, the `SealedSecret` may have been encrypted with a different public key and must be sealed again with the correct certificate/key pair.

### `kubectl delete pod ... -l name=sealed-secrets-controller` → *No resources found*

Documentação antiga do Sealed Secrets usa esse label; no **Helm chart Bitnami** (como neste repo), os pods têm labels `app.kubernetes.io/name=sealed-secrets` (e o *Deployment* costuma ser `sealed-secrets`). Use:

```bash
kubectl rollout restart deployment/sealed-secrets -n sealed-secrets
```

ou `kubectl delete pod -n sealed-secrets -l app.kubernetes.io/name=sealed-secrets`.

## Installing the `kubeseal` CLI

The `kubeseal` command-line tool is used to create `SealedSecret` resources from regular Kubernetes `Secret` manifests. You need to install it on your local machine where you run `kubectl`.

**Installation methods:**

- **Linux (amd64):**
  ```bash
  wget https://github.com/bitnami-labs/sealed-secrets/releases/download/v<VERSION>/kubeseal-<VERSION>-linux-amd64.tar.gz
  tar -xvzf kubeseal-<VERSION>-linux-amd64.tar.gz kubeseal
  sudo install -m 755 kubeseal /usr/local/bin/kubeseal
  ```
  _(Replace `<VERSION>` with the desired release version, e.g., `0.29.0`)_

## Using `kubeseal` to Encrypt Secrets

Once `kubeseal` is installed and your Sealed Secrets controller is running in the cluster (with its key available), you can encrypt secrets.

1.  **Create a standard Kubernetes Secret manifest** (e.g., `my-secret.yaml`), but **do not apply it to the cluster directly**.

    ```yaml
    # my-secret.yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: mysecret
      namespace: mynamespace
    type: Opaque
    data:
      foo: YmFy # "bar" base64 encoded
    ```

2.  **Use `kubeseal` to encrypt the secret:**

    `kubeseal` fetches the public key from the controller running in the cluster to perform the encryption.

    ```bash
    # Ensure your kubectl context points to the correct cluster and namespace
    # where the sealed-secrets controller runs (usually kube-system)

    # Encrypt the secret file
    kubeseal < my-secret.yaml > my-sealed-secret.yaml

    # Or pipe directly from kubectl create secret
    kubectl create secret generic mysecret --namespace mynamespace --from-literal=foo=bar --dry-run=client -o yaml | kubeseal > my-sealed-secret.yaml

    # Encrypt the secret file using the public key file (useful for offline/CI scenarios)
    kubeseal --cert pub-sealed-secrets.pem < my-secret.yaml > my-sealed-secret.yaml

    # Or pipe directly from kubectl create secret
    kubectl create secret generic mysecret --namespace mynamespace --from-literal=foo=bar --dry-run=client -o yaml | kubeseal --cert pub-sealed-secrets.pem > my-sealed-secret.yaml
    ```

    _Optional flags:_

    - `--controller-name`: Specify the name of the controller if not `sealed-secrets-controller`.
    - `--controller-namespace`: Specify the namespace of the controller if not `kube-system`.
    - `--fetch-cert`: Force fetching the public key certificate from the controller service URL instead of relying on `kubectl proxy`.
    - `--scope`: Control the scope of the sealed secret (e.g., `namespace-wide`, `cluster-wide`). Default is `strict` (only the original name and namespace).

3.  **Commit `my-sealed-secret.yaml` to your Git repository.** This file contains the encrypted data and is safe to store publicly.

4.  **Apply the `SealedSecret` to your cluster:**

    ```bash
    kubectl apply -f my-sealed-secret.yaml
    ```

The Sealed Secrets controller running in the cluster will detect the `SealedSecret` resource, decrypt it using its private key, and create a standard Kubernetes `Secret` named `mysecret` in the `mynamespace` namespace.
