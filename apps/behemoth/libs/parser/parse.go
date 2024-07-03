package main

import "C"
import (
	"fmt"
	"github.com/antlr4-go/antlr/v4"
	plsqlparser "github.com/bytebase/plsql-parser/parser"
	"strings"
)

//export Parse
func Parse(rawSql *C.char) *C.char {
	var result string
	sql := C.GoString(rawSql)
	input := antlr.NewInputStream(sql)
	lexer := plsqlparser.NewPlSqlLexer(input)
	stream := antlr.NewCommonTokenStream(lexer, 0)
	p := plsqlparser.NewPlSqlParser(stream)
	p.BuildParseTrees = true
	for _, v := range p.Sql_script().AllUnit_statement() {
		text := input.GetText(v.GetStart().GetStart(), v.GetStop().GetStop())
		text = strings.ReplaceAll(text, "\\s", " ")
		result += fmt.Sprintf("%s\n", text)
	}
	return C.CString(result)
}

func main() {}
