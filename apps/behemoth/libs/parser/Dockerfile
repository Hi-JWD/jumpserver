# 使用 Ubuntu 18.04 作为基础镜像（默认 GLIBC 版本为 2.27）
FROM ubuntu:18.04

RUN apt-get update && apt-get install -y \
    wget \
    gcc \
    g++ \
    make

# 下载并安装 Go 1.20
RUN wget https://golang.org/dl/go1.20.5.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.20.5.linux-amd64.tar.gz && \
    ln -s /usr/local/go/bin/go /usr/local/bin/go

# 设置 Go 环境变量
ENV PATH="/usr/local/go/bin:${PATH}"

# 复制并编译你的 Go 项目
COPY . /myapp
WORKDIR /myapp
RUN go build -o parse_linux.so -buildmode=c-shared parse.go

CMD ["/bin/bash"]
