go build -o parse_linux.so -buildmode=c-shared cmd/parse.go

go build -o parse_darwin.so -buildmode=c-shared cmd/parse.go
