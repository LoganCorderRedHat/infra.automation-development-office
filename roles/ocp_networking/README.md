# Role: infra.ado.ocp_networking

Centralized OpenShift networking orchestration role. Translates administrator
networking intent from PreFlight into supported OpenShift resources including
tenant networks (UDN/CUDN), security policies (NetworkPolicy,
AdminNetworkPolicy, BaselineAdminNetworkPolicy), physical networks (NMState),
load balancing (MetalLB), and egress resources (EgressIP, EgressFirewall).

This role coordinates the dependency-ordered execution of subordinate roles
and does not require OpenShift Virtualization to be selected.

## Role Author

Automation Development Office

## ✅ Role Requirements

- OpenShift cluster with OVN-Kubernetes network provider
- `kubernetes.core` collection
- `infra.ado` collection (subordinate roles)

## 📦 Role Variables

| Variable | Default | Description |
|---|---|---|
| `ocp_networking_enabled` | `false` | Master enable for networking |
| `ocp_networking_ocp_version` | `"4.17"` | Target OpenShift version |
| `ocp_networking_network_provider` | `"OVNKubernetes"` | Cluster network provider |
| `ocp_networking_tenants` | `[]` | List of tenant definitions |
| `ocp_networking_cluster_security` | `{}` | Cluster-level admin policies |
| `ocp_networking_physical_networks` | `[]` | Physical network definitions |
| `ocp_networking_ingress` | `{}` | Ingress configuration |
| `ocp_networking_load_balancing` | `{}` | MetalLB configuration |
| `ocp_networking_validate_provider` | `true` | Validate OVN-Kubernetes |
| `ocp_networking_create_namespaces` | `true` | Create tenant namespaces |
| `ocp_networking_apply_network_resources` | `true` | Apply UDN/CUDN/NAD |
| `ocp_networking_apply_security_policies` | `true` | Apply security policies |
| `ocp_networking_apply_egress_resources` | `true` | Apply egress resources |

## 🚀 Role Usage

```yaml
- hosts: localhost
  roles:
    - role: infra.ado.ocp_networking
      vars:
        ocp_networking_enabled: true
        ocp_networking_tenants:
          - tenant_name: finance
            namespaces:
              - name: finance-apps
                create: true
                labels: {}
            networks:
              - name: finance-network
                scope: cluster
                resource_type: ClusterUserDefinedNetwork
                role: Primary
                topology: Layer2
                subnets:
                  - cidr: "10.100.10.0/24"
                ipam:
                  lifecycle: Persistent
                namespace_selector:
                  matchLabels:
                    tenant: finance
            security:
              network_policy:
                enabled: true
                template: default-deny
```

## 🧪 Role Molecule Testing

```bash
cd extensions/molecule && ln -sfn . molecule
molecule test -s ocp_networking
```

## 📁 Role Structure

```
roles/ocp_networking/
├── defaults/
│   └── main.yml
├── meta/
│   └── main.yml
├── tasks/
│   ├── main.yml
│   ├── tenant_network.yml
│   ├── cluster_security.yml
│   ├── tenant_security.yml
│   └── tenant_egress.yml
└── README.md
```
