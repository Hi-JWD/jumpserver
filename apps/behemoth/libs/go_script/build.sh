#!/bin/bash

arch="amd64"
output_name="jms_cli"
#### Mac
echo "1. 编译 Mac 版本脚本"
bash -c "CGO_ENABLED=0 GOOS=darwin GOARCH=$arch go build -o ${output_name}_mac script.go"
echo "编译 Mac 版本脚本成功"

# 暂不支持
#echo ""
#### Windows
#echo "2. 编译 Windows 版本脚本"
#bash -c "CGO_ENABLED=0 GOOS=windows GOARCH=$arch go build -o ${output_name}_windows.exe script.go"
#echo "编译 Windows 版本脚本成功"

echo ""
#### Linux
echo "2. 编译 Linux 版本脚本"
bash -c "CGO_ENABLED=0 GOOS=linux GOARCH=$arch go build -o ${output_name}_linux script.go"
echo "编译 Linux 版本脚本成功"