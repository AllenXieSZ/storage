set -x
dnf install -y lustre-client >/dev/null 2>&1
rpm -qa | grep -i lustre
uname -r
lfs --version
