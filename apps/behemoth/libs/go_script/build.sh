#!/bin/bash

set -e

arch="amd64"
output_name="jms_cli"
IMAGE_NAME="jms_script"
IMAGE_TAG="v1"
#### Mac
echo "编译 Mac 版本脚本"
bash -c "CGO_ENABLED=1 GOOS=darwin GOARCH=$arch go build -o ${output_name}_darwin script.go"

echo ""
#### Linux
echo "编译 Linux 版本脚本"
if docker images | grep -q "${IMAGE_NAME}[[:space:]]*${IMAGE_TAG}"; then
  echo "镜像 ${IMAGE_NAME}:${IMAGE_TAG} 已经存在，跳过构建镜像"
else
  echo "镜像不存在，先构建镜像!"
  bash -c "docker build -t jms_script:v1 ."
fi
bash -c "docker run --rm -v $(pwd):/script jms_script:v1 sh build_linux.sh"