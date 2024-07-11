FROM registry.access.redhat.com/ubi8/ubi:8.6

WORKDIR /script

RUN yum update -y && yum install -y wget gcc tar && yum clean all

RUN wget https://golang.org/dl/go1.21.12.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.21.12.linux-amd64.tar.gz && \
    rm go1.21.12.linux-amd64.tar.gz

ENV GOROOT=/usr/local/go
ENV GOPATH=/go
ENV PATH=$GOROOT/bin:$GOPATH/bin:$PATH
ARG GOPROXY=https://goproxy.io

COPY . .

RUN go mod tidy

CMD ["/bin/sh"]
