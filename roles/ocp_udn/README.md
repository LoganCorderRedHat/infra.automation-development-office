# Role: infra.ado.ocp_udn

Manage UserDefinedNetwork (UDN), ClusterUserDefinedNetwork (CUDN), and
NetworkAttachmentDefinition (NAD) resources for OpenShift OVN-Kubernetes
networking.

Supports Layer2, Layer3, and Localnet topologies with Primary and
Secondary roles. Requires OVN-Kubernetes network provider.

## Role Author

Automation Development Office

## ✅ Role Requirements

- OpenShift cluster with OVN-Kubernetes network provider
- `kubernetes.core` collection

## 📦 Role Variables

| Variable | Default | Description |
|---|---|---|
| `ocp_udn_networks` | `[]` | List of network definitions |
| `ocp_udn_state` | `present` | Desired state |

Each network item supports: `name`, `scope`, `resource_type`, `role`,
`topology`, `namespaces`, `namespace_selector`, `subnets`, `ipam`,
`physical_network`, `join_subnets`.

## 🚀 Role Usage

```yaml
- hosts: localhost
  roles:
    - role: infra.ado.ocp_udn
      vars:
        ocp_udn_networks:
          - name: app-network
            scope: namespace
            resource_type: UserDefinedNetwork
            role: Secondary
            topology: Layer2
            namespaces:
              - my-namespace
            subnets:
              - cidr: "10.200.0.0/16"
```

## 🧪 Role Molecule Testing

```bash
cd extensions/molecule && ln -sfn . molecule
molecule test -s ocp_udn
```

## 📁 Role Structure

```
roles/ocp_udn/
├── defaults/
│   └── main.yml
├── meta/
│   └── main.yml
├── tasks/
│   ├── main.yml
│   ├── create_userdefinednetwork.yml
│   ├── create_clusteruserdefinednetwork.yml
│   └── create_networkattachmentdefinition.yml
└── README.md
```
