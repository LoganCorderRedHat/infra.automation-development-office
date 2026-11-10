# Role: infra.automation_development_office.ocp_mce_install

Install the multicluster engine Operator (MCE) and its MultiClusterEngine
resource on OpenShift, then wait for it and the HyperShift Operator.

## Role Author

Automation Development Office

## ✅ Role Requirements

- OpenShift API access (`kubernetes.core`) with permission to create
  namespaces, OperatorGroups, Subscriptions, and MultiClusterEngines
- The `multicluster-engine` package in a catalog source (mirror it on
  disconnected clusters)

## 📦 Role Variables

| Variable | Description |
|----------|-------------|
| `ocp_mce_install_channel` | Subscription channel, for example `stable-2.17`. Empty uses the package's default channel |
| `ocp_mce_install_source` / `ocp_mce_install_source_namespace` | Catalog source. Empty uses the one that serves the package |
| `ocp_mce_install_namespace` | Install namespace (default `multicluster-engine`) |
| `ocp_mce_install_instance_name` | MultiClusterEngine name (default `multiclusterengine`) |
| `ocp_mce_install_wait_hypershift` | Wait for the HyperShift Operator deployment in `hypershift` (default `true`) |
| `ocp_mce_install_operator_timeout` / `ocp_mce_install_instance_timeout` / `ocp_mce_install_hypershift_timeout` | Wait limits in seconds |

Existing installations are reused and not changed: when a MultiClusterEngine
exists, or a Subscription for `multicluster-engine` exists, or ACM's
MultiClusterHub manages MCE, the role only waits for it to be Available. The
hosted control planes component is enabled by default in the
MultiClusterEngine, so the HyperShift Operator starts without extra settings.

Shift on Shift (`ocp_hcp_kubevirt_cluster` with
`ocp_hcp_kubevirt_cluster_install_prerequisites: true`) calls this role and
picks the channel from the hosted control planes support matrix.

## 🚀 Role Usage

```yaml
- hosts: localhost
  gather_facts: false
  roles:
    - role: infra.automation_development_office.ocp_mce_install
      vars:
        ocp_mce_install_channel: stable-2.17
```

## 🧪 Role Molecule Testing

No Molecule scenario ships with this role; installing an operator needs a
live cluster. The role is exercised by the Shift on Shift deploy job when
install_prerequisites is on, and by the live `extensions/molecule/ocp_hcp_kubevirt`
scenario.

## 📁 Role Structure

```text
roles/ocp_mce_install/
  README.md
  defaults/main.yml
  meta/main.yml
  tasks/main.yml
```
