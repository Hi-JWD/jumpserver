package main

import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/creack/pty"
	_ "github.com/go-sql-driver/mysql"
)

const (
	MySQLPrefix = "mysql> "
	RetryTime   = 3
)

type LocalCommand struct {
	command string
	argv    []string

	cmd       *exec.Cmd
	ptyFd     *os.File
	ptyClosed chan struct{}

	ptyWin *pty.Winsize
}

func NewLocalCommand(command string, argv []string) (*LocalCommand, error) {
	ptyClosed := make(chan struct{})
	lCmd := &LocalCommand{
		command:   command,
		argv:      argv,
		ptyClosed: ptyClosed,
	}

	cmd := exec.Command(command, argv...)
	ptyFd, err := pty.StartWithSize(cmd, lCmd.ptyWin)
	if err != nil {
		return nil, fmt.Errorf("%w", err)
	}
	lCmd.cmd = cmd
	lCmd.ptyFd = ptyFd
	go func() {
		defer func() {
			_ = lCmd.ptyFd.Close()
			close(lCmd.ptyClosed)
		}()
		_ = lCmd.cmd.Wait()
	}()

	return lCmd, nil
}

func (lCmd *LocalCommand) Read(p []byte) (n int, err error) {
	return lCmd.ptyFd.Read(p)
}

func (lCmd *LocalCommand) Write(p []byte) (n int, err error) {
	return lCmd.ptyFd.Write(p)
}

func (lCmd *LocalCommand) Close() error {
	select {
	case <-lCmd.ptyClosed:
		return nil
	default:
		if lCmd.cmd != nil && lCmd.cmd.Process != nil {
			return lCmd.cmd.Process.Signal(syscall.SIGKILL)
		}
	}
	return nil
}

func (lCmd *LocalCommand) SetWinSize(width int, height int) error {
	win := pty.Winsize{
		Rows: uint16(height),
		Cols: uint16(width),
	}
	return pty.Setsize(lCmd.ptyFd, &win)
}

type BaseHandler interface {
	Connect() error
	DoCommand(command string) (string, error)
	Close()
}

type ScriptHandler struct {
	opts CmdOptions

	lCmd *LocalCommand
}

func (s *ScriptHandler) Connect() error {
	lCmd, _ := NewLocalCommand(s.opts.Script, s.opts.ScriptArgs)
	s.lCmd = lCmd

	time.Sleep(time.Second * 1)
	prompt := make([]byte, 1024)
	for {
		n, _ := lCmd.Read(prompt)
		if strings.Contains(string(prompt[:n]), MySQLPrefix) {
			break
		}
	}
	return nil
}

func (s *ScriptHandler) DoCommand(command string) (string, error) {
	result := ""
	_, err := s.lCmd.Write([]byte(command + "\n"))
	if err != nil {
		return "", err
	}
	for {
		r := make([]byte, 1024)
		n, _ := s.lCmd.Read(r)
		line := string(r[:n])
		if strings.Contains(line, MySQLPrefix) {
			break
		}
		result += string(r[:n])
	}
	return result, nil
}

func (s *ScriptHandler) Close() {
	_ = s.lCmd.Close()
}

type MySQLHandler struct {
	opts CmdOptions

	db *sql.DB
}

func (s *MySQLHandler) Connect() error {
	dsn := fmt.Sprintf(
		"%s:%s@tcp(%s:%s)/%s", s.opts.Auth.Username, s.opts.Auth.Password,
		s.opts.Auth.Address, s.opts.Auth.Port, s.opts.Auth.DBName,
	)
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return err
	}
	s.db = db
	return nil
}

func (s *MySQLHandler) DoCommand(command string) (string, error) {
	r, err := s.db.Exec(command)
	if err != nil {
		return "", err
	}
	affected, _ := r.RowsAffected()
	return fmt.Sprintf("Affected rows: %v", affected), nil
}

func (s *MySQLHandler) Close() {
	_ = s.db.Close()
}

func getHandler(opts CmdOptions) BaseHandler {
	switch opts.CmdType {
	case "mysql":
		return &MySQLHandler{opts: opts}
	case "script":
		return &ScriptHandler{opts: opts}
	}
	return nil
}

type Cmd struct {
	ID    string `json:"id"`
	Value string `json:"input"`
}

type Auth struct {
	Address  string `json:"address"`
	Port     int    `json:"port"`
	Username string `json:"username"`
	Password string `json:"password"`
	DBName   string `json:"db_name"`
}

type CmdOptions struct {
	CommandBase64 string `json:"-"`

	TaskID      string   `json:"task_id"`
	Host        string   `json:"host"`
	Token       string   `json:"token"`
	OrgId       string   `json:"org_id"`
	Script      string   `json:"script"`
	ScriptArgs  []string `json:"script_args"`
	Auth        Auth     `json:"auth"`
	CmdType     string   `json:"cmd_type"`
	CmdFilepath string   `json:"cmd_filepath"`
	CmdSet      []Cmd    `json:"command_set"`
	Encrypted   bool     `json:"encrypted_data"`
}

func (co *CmdOptions) ValidCmdType() bool {
	validType := []string{"mysql", "oracle", "script"}
	for _, vType := range validType {
		if co.CmdType == vType {
			return true
		}
	}
	return false
}

func (co *CmdOptions) aesCBCDecrypt(ciphertext []byte) ([]byte, error) {
	block, err := aes.NewCipher([]byte(co.Token[:32]))
	if err != nil {
		return nil, err
	}

	padding := len(ciphertext) % aes.BlockSize
	if padding > 0 {
		ciphertext = ciphertext[:len(ciphertext)-padding]
	}

	mode := cipher.NewCBCDecrypter(block, ciphertext[:aes.BlockSize])
	plaintext := make([]byte, len(ciphertext)-aes.BlockSize)
	mode.CryptBlocks(plaintext, ciphertext[aes.BlockSize:])
	return plaintext, nil
}

func (co *CmdOptions) ParseCmdFile() error {
	if _, err := os.Stat(co.CmdFilepath); err != nil {
		return fmt.Errorf("命令文件不存在: %s", err)
	}

	text, err := os.ReadFile(co.CmdFilepath)
	if err != nil {
		return fmt.Errorf("读取命令文件内容失败: %s", err)
	}
	if co.Encrypted {
		if text, err = co.aesCBCDecrypt(text); err != nil {
			return err
		}
	}
	err = json.Unmarshal(text, &co)
	if err != nil {
		return err
	}
	return nil
}

func (co *CmdOptions) Valid() error {
	rawCommand, err := base64.StdEncoding.DecodeString(co.CommandBase64)
	if err != nil {
		return err
	}

	if err = json.Unmarshal(rawCommand, &co); err != nil {
		return err
	}

	if err = co.ParseCmdFile(); err != nil {
		return fmt.Errorf("命令集合解析失败: %s", err)
	}

	if ok := co.ValidCmdType(); !ok {
		return fmt.Errorf("不支持的命令类型: %s", co.CmdType)
	}
	return nil
}

type BehemothClient struct {
	host  string
	token string
	orgId string

	client *http.Client
}

func NewBehemothClient(host, token, orgId string) *BehemothClient {
	return &BehemothClient{
		host: host, token: token, orgId: orgId,
		client: &http.Client{},
	}
}

func (b *BehemothClient) Get(url string) ([]byte, error) {
	request, err := http.NewRequest("GET", b.host+url, nil)
	if err != nil {
		return nil, err
	}
	request.Header.Add("Authorization", b.token)
	resp, err := b.client.Do(request)
	if err != nil {
		return nil, err
	}
	defer func(Body io.ReadCloser) {
		_ = Body.Close()
	}(resp.Body)

	body, _ := io.ReadAll(resp.Body)
	return body, nil
}

func (b *BehemothClient) Post(url string, data map[string]interface{}) ([]byte, error) {
	byteData, _ := json.Marshal(data)
	request, err := http.NewRequest(
		"POST", b.host+url, bytes.NewReader(byteData),
	)
	if err != nil {
		return nil, err
	}
	request.Header.Add("Authorization", "Bearer "+b.token)
	request.Header.Add("X-JMS-ORG", b.orgId)
	resp, err := b.client.Do(request)
	if err != nil {
		return nil, err
	}
	defer func(body io.ReadCloser) {
		_ = body.Close()
	}(resp.Body)

	body, _ := io.ReadAll(resp.Body)
	return body, nil
}

type TaskResponse struct {
	Status bool `json:"status"`
}

func (b *BehemothClient) HealthFeedback(taskID string) {
	var err error
	data := make(map[string]interface{})
	data["action"] = "health"

	url := fmt.Sprintf("/api/plans/executions/%s/", taskID)
	for i := 0; i < RetryTime; i++ {
		_, err = b.Post(url, data)
		if err == nil {
			break
		}
		time.Sleep(10 * time.Second)
	}
}

func (b *BehemothClient) OperateTask(taskID, action string) error {
	data := make(map[string]interface{})
	data["action"] = action

	bodyBytes, err := b.Post(fmt.Sprintf("/api/plans/tasks/%s/", taskID), data)
	if err != nil {
		return err
	}

	var response TaskResponse
	err = json.Unmarshal(bodyBytes, &response)
	if err != nil {
		return err
	}
	if action == "start" {
		go b.HealthFeedback(taskID)
	}
	return nil
}

func (b *BehemothClient) CommandCallback(
	taskID string, command *Cmd, result string, err error,
) (*TaskResponse, error) {

	data := make(map[string]interface{})
	data["command_id"] = command.ID
	if err != nil {
		data["status"] = false
		data["result"] = err.Error()
	} else {
		data["status"] = true
		data["result"] = result
	}

	url := fmt.Sprintf("/api/plans/tasks/%s/", taskID)
	bodyBytes, err := b.Post(url, data)
	if err != nil {
		return nil, err
	}

	var response TaskResponse
	err = json.Unmarshal(bodyBytes, &response)
	if err != nil {
		return nil, err
	}
	return &response, nil
}

func GetLogger(taskId string) *log.Logger {
	_, filename, _, _ := runtime.Caller(0)
	scriptDir := filepath.Dir(filename)
	logFile := filepath.Join(scriptDir, fmt.Sprintf("%v-bs.log", taskId))
	f, err := os.OpenFile(logFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
	if err != nil {
		fmt.Printf("error opening file: %v", err)
	}
	return log.New(f, "LOG: ", log.Ldate|log.Ltime|log.Lshortfile)
}

func main() {
	opts := CmdOptions{}
	flag.StringVar(&opts.CommandBase64, "command", opts.CommandBase64, "命令")
	// 解析命令行标志
	flag.Parse()
	if err := opts.Valid(); err != nil {
		fmt.Printf("参数校验错误: %v\n", err)
		return
	}

	logger := GetLogger(opts.TaskID)
	bClient := NewBehemothClient(opts.Host, opts.Token, opts.OrgId)

	if err := bClient.OperateTask(opts.TaskID, "start"); err != nil {
		logger.Fatalf("Task launch failed: %v\n", err)
	}
	handler := getHandler(opts)
	if err := handler.Connect(); err != nil {
		_ = bClient.OperateTask(opts.TaskID, "stop")
		logger.Fatalf("Task connect failed: %v\n", err)
	}

	for _, command := range opts.CmdSet {
		result, err := handler.DoCommand(command.Value)
		resp, err := bClient.CommandCallback(opts.TaskID, &command, result, err)
		if err != nil {
			logger.Fatalf("Command callback failed: %v\n", err)
		}
		if !resp.Status {
			_ = bClient.OperateTask(opts.TaskID, "stop")
			logger.Fatalf(
				"Not allow to continue executing commands[Status: %v, error: %v]", resp.Status, err,
			)
		}
	}
}
