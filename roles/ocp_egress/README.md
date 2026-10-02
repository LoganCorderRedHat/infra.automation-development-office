# Role: infra.ado.ocp_egress

Manage OpenShift egress resources including EgressIP and EgressFirewall.

## Role Author

Automation Development Office

## ✅ Role Requirements

- OpenShift cluster with OVN-Kubernetes network provider
- `kubernetes.core` collection

## 📦 Role Variables

| Variable | Default | Description |
|---|---|---|
| `ocp_egress_resources` | `[]` | List of egress resources |
| `ocp_egress_state` | `present` | Desired state |

Each resource must include `kind`, `name`, and `spec`. EgressFirewall
requires `namespace`. Only one EgressFirewall per namespace is allowed.

## 🚀 Role Usage

```yaml
- hosts: localhost
  roles:
    - role: infra.ado.ocp_egress
      vars:
        ocp_egress_resources:
          - kind: EgressFirewall
            name: default
            namespace: my-namespace
            spec:
              egress:
                - type: Allow
                  to:
                    cidrSelector: 10.0.0.0/8
                - type: Deny
                  to:
                    cidrSelector: 0.0.0.0/0
```

## 🧪 Role Molecule Testing

```bash
cd extensions/molecule && ln -sfn . molecule
molecule test -s ocp_egress
```

## 📁 Role Structure

```
roles/ocp_egress/
├── defaults/
│   └── main.yml
├── meta/
│   └── main.yml
├── tasks/
│   └── main.yml
└── README.md
```
