#!/bin/bash
# t5watch.sh : 打印 spool 状态（.part 大小、ready 文件）
S=/var/spool/lustre-changelog; date -u +%T; ls -la $S/*.part 2>/dev/null; echo ready=$(ls $S/ready | wc -l); ls -la $S/ready | tail -n +4
