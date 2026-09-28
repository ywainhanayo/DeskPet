"""chat_client.py —— DeepSeek 对话客户端(阶段2)。

接口 = OpenAI 兼容的 /chat/completions,Bearer 鉴权。
模型默认 deepseek-flash = DeepSeek-V4.1-Flash(2026-09-10 上线的快速旗舰,
官方文档 https://api-docs.deepseek.com),config 的 `model` 键可换
(如 deepseek-v4-pro);旧名 deepseek-chat 已不是当前主推型号。

共用聊天规则走 soul.md,每个角色的自动检索设定走 personas/<角色ID>.md;
用户随时可手改,每次发送都现读(改完即生效,不用重启)。
模板里 {name}/{user_title} 是两个槽位:角色叫什么、称呼用户什么。
所有失败(无key/断网/超时/HTTP错误/响应格式不对)都转成给用户看的中文文案
经 reply_failed 交付:不抛异常、不弹错误框。
"""

import json
import sys
from urllib.parse import quote

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

from . import pet_config

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"   # DeepSeek-V4.1-Flash;旧别名 deepseek-v4-flash 仍被官方接受
TIMEOUT_MS = 30000        # 单次请求超时
MAX_HISTORY = 10          # 带给模型的最近轮数(一轮 = 一问一答,超出裁掉)
MAX_REPLY_TOKENS = 500    # 配合人设"简短",也控住成本

# 角色设定生成的级联:①模型内置知识 → ②萌娘百科 API 资料 + 模型提炼。
# 两级都查不到(模型答 UNKNOWN 且 wiki 没有页面)就不写设定,soul 通用模板兜底。
WIKI_API = "https://mzh.moegirl.org.cn/api.php"
WIKI_UA = "DeskPet/0.1 (persona brief fetcher)"
WIKI_CHARS = 6000         # wiki 原文截断长度,控制 token
BRIEF_TOKENS = 400

PERSONA_META_PROMPT = """你是角色设定提炼器。请对角色「{name}」输出一份简短的中文角色设定,严格按以下五行格式,每行一项,冒号后直接写内容:
性格特点:
说话语气与方式:
口头禅:
自称:
和好友的相处模式:
只依据你的知识{source_hint}。若你根本不了解这个角色,整个回复只输出 UNKNOWN,绝不要编造。"""

# Qt 错误码统一转 int 再比较(PySide6 新式枚举 == 裸整数会失配,测试里也直接传整数)
_ERR_NO = int(QNetworkReply.NetworkError.NoError.value)
_ERR_HOST = int(QNetworkReply.NetworkError.HostNotFoundError.value)
_ERR_TIMEOUT = int(QNetworkReply.NetworkError.TimeoutError.value)
_ERR_CANCEL = int(QNetworkReply.NetworkError.OperationCanceledError.value)


def friendly_error(error, http_status) -> str:
    """(Qt 网络错误码, HTTP 状态码) → 给用户看的中文兜底文案。"""
    err = int(getattr(error, "value", error))   # 枚举或整数都接受
    if http_status == 401:
        return "API key 不对,右键桌宠打开「设置」检查一下?"
    if http_status == 402:
        return "DeepSeek 账户余额不足啦,去充值一下?"
    if http_status == 429:
        return "请求太快啦,歇一会儿再聊"
    if http_status is not None and http_status >= 500:
        return "DeepSeek 服务器打盹了,过会儿再试?"
    if http_status is not None and http_status >= 400:
        return f"请求被拒了(代码 {http_status}),过会儿再试?"
    if err == _ERR_HOST:
        return "断网了?我连不上 DeepSeek…"
    if err in (_ERR_TIMEOUT, _ERR_CANCEL):
        return "网络有点慢,再叫我一次?"
    if err != _ERR_NO:
        return "网络好像不太好,过会儿再试?"
    return "回复没读懂,再试一次?"   # 传输成功但响应格式不对


class ChatClient(QObject):
    reply_arrived = Signal(str)     # 成功:模型回复文本
    reply_failed = Signal(str)      # 失败:给用户看的中文文案
    busy_changed = Signal(bool)     # 请求开始/结束(桌宠用来切"闭眼在想"状态)
    persona_changed = Signal(str)   # 角色名变了(聊天窗口标题等跟随刷新)
    character_changed = Signal(str) # 切换角色时聊天窗口换到该角色的记录

    def __init__(self, api_key="", char_name="", user_title="主人", model="",
                 character_id=pet_config.DEFAULT_CHARACTER_ID, extra=""):
        super().__init__()
        self._api_key = api_key or ""
        self._char_name = char_name or "宠物"
        self._user_title = user_title or "主人"
        self._model = model or MODEL
        self._extra = extra or "" # 角色包的性格补充(拼在 soul 之后)
        self._character_id = character_id
        self._histories = {character_id: []}
        self._history = self._histories[character_id]  # 每个角色单独保留最近 10 轮
        self._pending_user = ""
        self._pending_character_id = character_id
        self._busy = False
        self._nam = QNetworkAccessManager(self)
        self.ensure_soul()       # 首次运行生成默认 soul.md

    # ---- 属性(设置对话框读) --------------------------------------------
    @property
    def api_key(self):
        return self._api_key

    @property
    def char_name(self):
        return self._char_name

    @property
    def user_title(self):
        return self._user_title

    @property
    def model(self):
        return self._model

    @property
    def character_id(self):
        return self._character_id

    @property
    def busy(self):
        return self._busy

    # ---- 配置 ------------------------------------------------------------
    def set_api_key(self, key):
        self._api_key = key or ""

    def set_persona(self, char_name, user_title, extra=None, character_id=None):
        new_id = character_id or self._character_id
        changed = new_id != self._character_id
        if changed:
            self._character_id = new_id
            self._history = self._histories.setdefault(new_id, [])
        self._char_name = char_name or self._char_name
        self._user_title = user_title or self._user_title
        if extra is not None:
            self._extra = extra or ""
        if changed:
            self.character_changed.emit(new_id)
        self.persona_changed.emit(self._char_name)

    @staticmethod
    def ensure_soul():
        pet_config.ensure_soul_file()

    def _soul_text(self):
        """每次现读共用规则；旧配置内嵌的角色区块不会进入共用提示词。"""
        try:
            with open(pet_config.SOUL_PATH, "r", encoding="utf-8") as f:
                text = f.read()
            if text.strip():
                return pet_config.split_soul(text)[0]
        except OSError:
            pass
        return pet_config.DEFAULT_SOUL_TEMPLATE

    def system_prompt(self):
        soul = (self._soul_text()
                .replace("{name}", self._char_name)
                .replace("{user_title}", self._user_title))
        persona = pet_config.persona_text(self._character_id)
        if persona:
            soul += "\n\n" + persona
        if self._extra:
            soul += "\n\n【角色补充设定】\n" + self._extra
        return soul

    def clear_history(self):
        self._history = []
        self._histories[self._character_id] = self._history

    # ---- 发送 ------------------------------------------------------------
    def send(self, user_text: str) -> bool:
        """发出一轮对话。返回是否真的发出去了(忙/空文本/无 key → False;
        无 key 时会先发一条 reply_failed 引导文案)。"""
        text = user_text.strip()
        if self._busy or not text:
            return False
        if not self._api_key:
            self.reply_failed.emit("还没有填 DeepSeek API key——右键桌宠打开「设置」填一个吧")
            return False
        messages = [{"role": "system", "content": self.system_prompt()}]
        messages += self._history[-2 * MAX_HISTORY:]
        messages.append({"role": "user", "content": text})
        body = json.dumps({
            "model": self._model,
            "messages": messages,
            "stream": False,
            "max_tokens": MAX_REPLY_TOKENS,
        }).encode("utf-8")
        req = QNetworkRequest(API_URL)
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        req.setRawHeader(b"Authorization", b"Bearer " + self._api_key.encode("utf-8"))
        req.setTransferTimeout(TIMEOUT_MS)
        reply = self._nam.post(req, body)
        reply.finished.connect(lambda: self._on_finished(reply))
        self._pending_user = text
        self._pending_character_id = self._character_id
        self._busy = True
        self.busy_changed.emit(True)
        return True

    def _on_finished(self, reply: QNetworkReply):
        self._busy = False
        self.busy_changed.emit(False)
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        status = int(status) if status is not None else None
        err = int(getattr(reply.error(), "value", reply.error()))
        raw = bytes(reply.readAll()).decode("utf-8", "replace")
        reply.deleteLater()

        if err != _ERR_NO or status != 200:
            print(f"[chat] HTTP {status} err={err}: {raw[:300]}", file=sys.stderr)
            self.reply_failed.emit(friendly_error(err, status))
            return
        try:
            data = json.loads(raw)
            text = data["choices"][0]["message"]["content"].strip()
            if not text:
                raise ValueError("empty content")
        except Exception:
            print(f"[chat] 响应格式异常: {raw[:300]}", file=sys.stderr)
            self.reply_failed.emit(friendly_error(
                QNetworkReply.NetworkError.NoError, None))
            return

        history = self._histories.setdefault(self._pending_character_id, [])
        history.append({"role": "user", "content": self._pending_user})
        history.append({"role": "assistant", "content": text})
        del history[:-2 * MAX_HISTORY]
        if self._pending_character_id == self._character_id:
            self.reply_arrived.emit(text)

    # ------------------------------------------------------------------
    # 角色设定检索(级联:①模型内置知识 ②萌娘百科资料+模型提炼)
    # ------------------------------------------------------------------
    def generate_persona_brief(self, char_name, done):
        """级联生成角色设定。done(ok: bool, text: str, source: str) 主线程回调;
        source: 'model'(内置知识) / 'wiki'(萌娘百科资料提炼) / ''(两级都没查到)。"""
        prompt = PERSONA_META_PROMPT.format(name=char_name, source_hint="")
        self._raw_chat([{"role": "user", "content": prompt}],
                       lambda text: self._persona_fallback(char_name, text, done))

    def _persona_fallback(self, char_name, text, done):
        brief = self._clean_brief(text)
        if brief:
            done(True, brief, "model")
            return
        if not self._api_key:
            done(False, "", "")   # ②的提炼也要模型,没 key 直接放弃,不白抓 wiki
            return
        self._wiki_extract(char_name, lambda wiki: self._persona_distill(char_name, wiki, done))

    def _persona_distill(self, char_name, wiki, done):
        if not wiki:
            done(False, "", "")
            return
        prompt = (PERSONA_META_PROMPT.format(name=char_name, source_hint="以及下面的资料")
                  + f"\n\n资料(来自萌娘百科,可能被截断):\n{wiki}")
        self._raw_chat([{"role": "user", "content": prompt}],
                       lambda text: done(bool(self._clean_brief(text)),
                                         self._clean_brief(text) or "", "wiki"))

    @staticmethod
    def _clean_brief(text):
        """UNKNOWN/空 → 失败;其余返回去空白后的简报。"""
        if not text:
            return ""
        t = text.strip()
        return "" if t.upper().startswith("UNKNOWN") else t

    def _raw_chat(self, messages, callback):
        """一次性内部调用(不动聊天历史/状态);任何失败 callback(None)。"""
        if not self._api_key:
            callback(None)
            return
        body = json.dumps({"model": self._model, "messages": messages,
                           "stream": False, "max_tokens": BRIEF_TOKENS}).encode("utf-8")
        req = QNetworkRequest(API_URL)
        req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        req.setRawHeader(b"Authorization", b"Bearer " + self._api_key.encode("utf-8"))
        req.setTransferTimeout(TIMEOUT_MS)
        reply = self._nam.post(req, body)

        def finished():
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            status = int(status) if status is not None else None
            err = int(getattr(reply.error(), "value", reply.error()))
            raw = bytes(reply.readAll()).decode("utf-8", "replace")
            reply.deleteLater()
            if err != _ERR_NO or status != 200:
                print(f"[persona] HTTP {status} err={err}: {raw[:200]}", file=sys.stderr)
                callback(None)
                return
            try:
                callback(json.loads(raw)["choices"][0]["message"]["content"].strip())
            except Exception:
                print(f"[persona] 响应格式异常: {raw[:200]}", file=sys.stderr)
                callback(None)

        reply.finished.connect(finished)

    def _wiki_extract(self, title, callback):
        """萌娘百科:按标题取纯文本正文(截断)后 callback;任何失败 callback("")。"""
        url = (f"{WIKI_API}?action=query&prop=extracts&explaintext=1"
               f"&titles={quote(title)}&format=json")
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", WIKI_UA.encode("utf-8"))
        req.setTransferTimeout(20000)
        reply = self._nam.get(req)

        def finished():
            raw = bytes(reply.readAll()).decode("utf-8", "replace")
            reply.deleteLater()
            try:
                pages = json.loads(raw)["query"]["pages"]
                page = next(iter(pages.values()))
                extract = (page.get("extract") or "").strip()
                if not extract or page.get("missing") is not None:
                    callback("")
                    return
                callback(extract[:WIKI_CHARS])
            except Exception:
                print(f"[persona] wiki 响应异常: {raw[:200]}", file=sys.stderr)
                callback("")

        reply.finished.connect(finished)
