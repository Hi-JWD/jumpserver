FROM golang:1.21.12-alpine3.20

WORKDIR /script

COPY . .

ARG APT_MIRROR=mirrors.ustc.edu.cn
# ARG APT_MIRROR=mirrors.aliyun.com
RUN sed -i "s@dl-cdn.alpinelinux.org@${APT_MIRROR}@g" /etc/apk/repositories \
    && apk update && apk add build-base

ARG GOPROXY=https://goproxy.io
RUN go mod tidy

CMD ["/bin/sh"]
