cd "$(dirname "$0")"
rm -rf /mnt/xfs/dutest/s2; date
bash ./s3.sh C 0 10000 10240
bash ./s3.sh A 10 50
bash ./s3.sh B 10 5000
