const zhixinUrlPrefix = '';
const defaultPerson = {
    //1-已登记人员，2-陌生人
    perType: -1,
    //存储手机号
    customId: '',
    personId: '',
    persionName: '',
    deviceKey: '',
    facesluiceId: '',
    pic: ''
}

let app = new Vue({
    el: "#app",
    delimiters:["[[","]]"],
    data() {
        return {
            clientIp: "",
            facesluiceId:"",
            wsurl:"",
            isSupportFaceLogin: false,
            isShowFaceContainer: false,                
            person: defaultPerson,
            isConfirmShow:false,
            errMsg:''
        }
    },
    watch: {
        isShowFaceContainer() {
            this.person = defaultPerson
        }
    },
    async mounted() {
        this.clientIp = await this.getClientIp();
        this.isSupportFaceLogin = await this.getSupportFaceLogin()
        console.log(this.clientIp)
        if(this.isSupportFaceLogin){
            this.initWebSocket()
        }
        
    },
    methods: {
        async getClientIp() {
            let url = zhixinUrlPrefix+"/p/main/get_client_ip"
            let res = await axios.get(url)
            return res.data.ip
        },
        async getSupportFaceLogin() {
            let url = zhixinUrlPrefix+"/p/webapi/request/0Z6gB4k7LUeTq/isSupportFaceLogin?ip="+this.clientIp
            let { data } = await axios.get(url)
            this.facesluiceId = data.facesluiceId;
            this.wsurl = data.wsurl
            return data.support
        },
        beforeLogin() {
            if (this.isSupportFaceLogin) {
                this.isShowFaceContainer = true
            }else{
                this.isShowFaceContainer = false
            }
        },
        initWebSocket() {
            //ws://172.16.42.37:5678
            let url = this.wsurl+'/websocket/facelogin/'+this.clientIp+this.facesluiceId+'?req=ok'
            console.log(url)
            this.ws = new WebSocket(url);
            this.ws.onopen = this.onOpen;
            this.ws.onmessage = this.onMessage;
            this.ws.onerror = this.onError;
            this.ws.onClose = this.onClose;
        },
        faceLogin() {
            // this.isShowFaceContainer = false
            if (!this.errMsg) {
                this.isShowFaceContainer = false
                $('#login-form').submit(); 
            }
        },
        onOpen() {
            console.log("连接成功！");
        },
        onMessage({ data }) {
            this.person = JSON.parse(data)
            var inputname = $('#id_username').val();
            if (this.person.perType == 2) return this.errMsg = '陌生人，请登记！'
            if (this.person.perType == 1 && inputname != this.person.customId ) return this.errMsg = "登录账号错误，请重新输入！"
            this.errMsg = ""
            this.isConfirmShow=true
        },
        onError(e) {
            console.log("WebSocket连接失败,请检查连接是否正确！");
        },
        onClose() { },
        close() {
            this.$refs.container.remove();
        },
    },
});