#!/bin/bash

arch="amd64"
output_name="behemoth_cli"

export cgo_enable=0
export GOARCH="amd64"
#### Mac
export GOOS="darwin"
echo "编译 Mac 版本脚本"
cmd="go build -o ${output_name}_mac script.go"
bash $cmd
echo "编译 Mac 版本脚本成功"

echo ""
#### Windows
export GOOS="windows"
echo "编译 Windows 版本脚本"
#go build -o ${output_name}_windows.exe script.go
echo "编译 Windows 版本脚本成功"

echo ""
#### Linux
export GOOS="linux"
echo "编译 Linux 版本脚本"
#go build -o ${output_name}_linux script.go
echo "编译 Linux 版本脚本成功"