# Resources — datasync-snapmirror-rootcause (us-east-2)

| Resource | ID | Notes |
|---|---|---|
| Source FSxN | fs-027217e10840009de | Gen2 SINGLE_AZ_2, 1HA, throughput 1536, storage 2048GB |
| Target FSxN | fs-07695c839cde46696 | Gen2 SINGLE_AZ_2, 1HA, throughput 1536, storage 1024GB |
| Loader EC2 | i-09d530edb2544dc9a | c6i.large, AL2023 x86_64, ohio key, SSM |
| Security Group | sg-07e321ff528ced7b0 | dsync-rootcause-sg, all VPC traffic + ssh |
| Subnet | subnet-0ebad2264c331f72b | us-east-2a, vpc-0c28d2a9082ef222e |

fsxadmin password: <REDACTED>

All tagged project=storage-bench-agent taskId=datasync-snapmirror-rootcause. **Resources retained per ROLE.md; ask 伟伟 before deleting.**
