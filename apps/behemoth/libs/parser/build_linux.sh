#!/bin/sh

set -e

echo "开始编译 Linux 版本脚本"
sh -c "go build -o parse_linux.so -buildmode=c-shared parse.go"