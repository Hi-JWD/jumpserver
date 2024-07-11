#!/bin/sh

set -e

arch="amd64"
output_name="jms_cli"
echo "开始编译 Linux 版本脚本"
sh -c "CGO_ENABLED=1 GOARCH=$arch go build -o ${output_name}_linux script.go"