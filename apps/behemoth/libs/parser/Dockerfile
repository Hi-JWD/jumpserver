# 使用官方的 golang 镜像作为基础镜像
FROM golang:1.20

# 设置工作目录
WORKDIR /app

# 复制当前目录下的所有文件到工作目录
COPY . .

# 安装交叉编译工具链（如果需要的话，比如在Linux上交叉编译到Windows）
# RUN apt-get update && apt-get install -y gcc-multilib

# 默认的启动命令，进入交互式shell
CMD ["/bin/bash"]
