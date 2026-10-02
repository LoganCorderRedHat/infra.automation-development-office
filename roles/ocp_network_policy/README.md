# Role: infra.ado.ocp_network_policy

Manage OpenShift network security policies including NetworkPolicy,
AdminNetworkPolicy, BaselineAdminNetworkPolicy, MultiNetworkPolicy, and
EgressFirewall resources.

## Role Author

Automation Development Office

## ✅ Role Requirements

- OpenShift cluster with OVN-Kubernetes network provider
- `kubernetes.core` collection

## 📦 Role Variables

| Variable | Default | Description |
|---|---|---|
| `ocp_network_policy_resources` | `[]` | List of policy resources |
| `ocp_network_policy_state` | `present` | Desired state |

Each resource must include `kind`, `name`, and `spec`. Namespace-scoped
kinds require `namespace`. The `apiVersion` is resolved automatically
per kind.

## 🚀 Role Usage

```yaml
- hosts: localhost
  roles:
    - role: infra.ado.ocp_network_policy
      vars:
        ocp_network_policy_resources:
          - kind: NetworkPolicy
            name: deny-all
            namespace: my-namespace
            spec:
              podSelector: {}
              policyTypes:
                - Ingress
                - Egress
```

## 🧪 Role Molecule Testing

```bash
cd extensions/molecule && ln -sfn . molecule
molecule test -s ocp_network_policy
```

## 📁 Role Structure

```
roles/ocp_network_policy/
├── defaults/
│   └── main.yml
├── meta/
│   └── main.yml
├── tasks/
│   └── main.yml
└── README.md
```
