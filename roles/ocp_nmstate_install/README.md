# Role: infra.ado.ocp_nmstate_install

Install the Kubernetes NMState Operator, create the NMState singleton
instance, and optionally apply NodeNetworkConfigurationPolicy (NNCP)
resources for physical node networking (bridges, bonds, VLANs).

**WARNING:** NNCP changes modify physical node network state. Incorrect
configuration can make nodes unreachable. Always review generated desired
state before applying in production.

## Role Author

Automation Development Office

## ✅ Role Requirements

- OpenShift cluster
- `kubernetes.core` collection
- `infra.ado` collection (ocp_operator_subscription, ocp_wait_operator)

## 📦 Role Variables

| Variable | Default | Description |
|---|---|---|
| `ocp_nmstate_namespace` | `openshift-nmstate` | Operator namespace |
| `ocp_nmstate_operator_name` | `kubernetes-nmstate-operator` | Operator package |
| `ocp_nmstate_operator_channel` | `stable` | OLM channel |
| `ocp_nmstate_instance_name` | `nmstate` | NMState CR name |
| `ocp_nmstate_physical_networks` | `[]` | Physical network definitions |
| `ocp_nmstate_apply_nncp` | `true` | Apply NNCP resources |
| `ocp_nmstate_nncp_wait_timeout` | `300` | NNCP wait timeout (seconds) |

## 🚀 Role Usage

```yaml
- hosts: localhost
  roles:
    - role: infra.ado.ocp_nmstate_install
      vars:
        ocp_nmstate_physical_networks:
          - name: datacenter-vlan
            bridge: br1
            node_selector:
              node-role.kubernetes.io/worker: ""
            interface_config:
              type: bridge
              interfaces:
                - ens224
```

## 🧪 Role Molecule Testing

```bash
cd extensions/molecule && ln -sfn . molecule
molecule test -s ocp_nmstate_install
```

## 📁 Role Structure

```
roles/ocp_nmstate_install/
├── defaults/
│   └── main.yml
├── meta/
│   └── main.yml
├── tasks/
│   ├── main.yml
│   └── create_nncp.yml
└── README.md
```
