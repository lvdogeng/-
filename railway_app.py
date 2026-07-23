"""
月白 AI Agent — Vercel / Netlify Serverless 版本
═══════════════════════════════════════════════════════════════
本版本针对 Vercel Serverless Functions 和 Netlify Functions 优化。
移除了本地持久化依赖:
  ✗ SQLite 文件  →  改用 内存 + Upstash Redis (可选)
  ✗ 本地 BGE 模型 → 改用 OpenAI Embeddings API
  ✗ ChromaDB      → 改用 内存向量库 (启动时从 DATA_JSON 加载)
  ✗ LangChain     → 改用 纯 OpenAI SDK
  ✗ CrewAI        → 改用 4 段 LLM 调用流水线

环境变量:
  DEEPSEEK_API_KEY       DeepSeek API Key (必需)
  DEEPSEEK_BASE_URL      默认 https://api.deepseek.com
  DEEPSEEK_MODEL         默认 deepseek-chat
  OPENAI_API_KEY         OpenAI API Key (用于嵌入向量)
  OPENAI_BASE_URL        默认 https://api.openai.com/v1
  KB_DATA_JSON           知识库内容 (JSON 字符串),可选
  ALLOW_ORIGIN           CORS 允许的来源,默认 *

学号：2325102015  姓名：黄凯豪
"""

import json
import os
import re
import uuid
import math
import time
import random
import string
import urllib.request
from datetime import datetime
from collections import defaultdict

from flask import Flask, request, Response, stream_with_context, send_from_directory, render_template
from flask_cors import CORS
from openai import OpenAI

# ════════════════════════════════════════════════════════════
#  Vercel 需要把静态资源指向 ../public,但我们项目用 ../static
#  如果用 Vercel,需要把 static/* 移到 public/*
# ════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════
#  配置
# ════════════════════════════════════════════════════════════
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", DEEPSEEK_API_KEY)
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_EMBED_MODEL = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# 内存会话存储 (serverless 每次冷启动会清空,生产环境应改用 Upstash Redis)
_sessions: dict = {}  # {session_id: {"messages": [...], "updated_at": ...}}
_users: dict = {}  # {name: uid}

# 内存向量库 (从 KB_DATA_JSON 环境变量加载)
_vector_store: list = []  # [{"id":..., "doc":..., "meta":..., "embedding":[...]}, ...]

# ════════════════════════════════════════════════════════════
#  Flask 应用
# ════════════════════════════════════════════════════════════
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app, resources={r"/*": {"origins": os.environ.get("ALLOW_ORIGIN", "*")}})


# ════════════════════════════════════════════════════════════
#  启动时加载知识库(从环境变量或默认示例)
# ════════════════════════════════════════════════════════════
def _load_kb_from_env():
    """从 KB_DATA_JSON 环境变量加载知识库,格式:[{doc, source, chunk_index?}]"""
    global _vector_store
    raw = os.environ.get("KB_DATA_JSON", "").strip()
    if not raw:
        # 默认占位数据
        raw = json.dumps([
            {"doc": "月白是一位温柔的睡前故事创作师,擅长写柔和、有质感的文字,把读者送入安稳的睡眠。", "source": "README.md"},
            {"doc": "睡前故事创作铁律:安全感第一,主角限定为小动物或自然精灵,情节只有愿望→旅程→归来。", "source": "rules.md"},
            {"doc": "禁止使用突然、猛地、哭、怕、黑等字眼。五感优先,节奏递减,句式交替。", "source": "rules.md"},
            {"doc": "Cloudflare Pages 是 Cloudflare 的静态网站托管服务,支持全球 CDN、SSL、Functions。", "source": "cloudflare.md"},
            {"doc": "Vercel 是 Next.js 团队的 serverless 平台,对 Python/Node/Go Serverless Functions 支持完善。", "source": "vercel.md"},
            {"doc": "Netlify 是流行的 Jamstack 平台,提供 Forms、Functions、Identity 等服务。", "source": "netlify.md"},
        ], ensure_ascii=False)
    try:
        items = json.loads(raw)
        _vector_store = [{"id": f"d{i}", "doc": it["doc"], "meta": it.get("source", "default")}
                         for i, it in enumerate(items)]
        # 启动时不立即向量化(避免启动太慢),改为首次查询时懒加载
    except Exception as e:
        print(f"[KB 加载失败] {e}")
        _vector_store = []


_load_kb_from_env()


# ════════════════════════════════════════════════════════════
#  LLM 客户端
# ════════════════════════════════════════════════════════════
llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
embed_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


def _embed_text(text: str):
    """使用 OpenAI Embeddings API 获取向量"""
    try:
        resp = embed_client.embeddings.create(model=OPENAI_EMBED_MODEL, input=text)
        return resp.data[0].embedding
    except Exception as e:
        print(f"[嵌入失败] {e}")
        return None


def _cosine(a, b):
    if not a or not b:
        return 0.0
    s = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return s / (na * nb) if na and nb else 0.0


def _ensure_kb_vectors():
    """懒加载:首次检索时计算所有文档的向量"""
    if not _vector_store:
        return
    if "embedding" in _vector_store[0]:
        return
    for item in _vector_store:
        item["embedding"] = _embed_text(item["doc"])


def hybrid_search(query: str, top_k: int = 3):
    """混合检索:余弦相似度(无 BM25 / Rerank,简化版)"""
    _ensure_kb_vectors()
    if not _vector_store:
        return [], [], []
    q_emb = _embed_text(query)
    if not q_emb:
        return [], [], []
    scored = []
    for item in _vector_store:
        if "embedding" not in item or not item["embedding"]:
            continue
        sim = _cosine(q_emb, item["embedding"])
        scored.append((sim, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]
    docs = [it["doc"] for _, it in top]
    sources = [it["meta"] for _, it in top]
    scores = [f"余弦={s:.3f}" for s, _ in top]
    return docs, sources, scores


# ════════════════════════════════════════════════════════════
#  工具函数
# ════════════════════════════════════════════════════════════
def execute_tool(name: str, args: dict):
    if name == "get_current_time":
        return datetime.now().strftime(args.get("format", "%Y-%m-%d %H:%M:%S"))
    elif name == "calculate":
        try:
            return f"结果: {eval(args.get('expression', ''), {'__builtins__': {}}, {})}"
        except Exception as e:
            return f"计算错误: {e}"
    elif name == "roll_dice":
        sides, count = int(args.get("sides", 6)), int(args.get("count", 1))
        results = [random.randint(1, sides) for _ in range(count)]
        return f"掷出 {count} 个 {sides} 面骰子: [{', '.join(map(str, results))}] 总和={sum(results)}"
    elif name == "get_moon_phase":
        city = args.get("city", "北京")
        try:
            req = urllib.request.Request(
                f"https://wttr.in/{city}?format=%m",
                headers={"User-Agent": "curl/7.79"}
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                return f"{city} 今晚月相: {r.read().decode('utf-8').strip()}"
        except Exception:
            phases = ["🌑 新月", "🌒 蛾眉月", "🌓 上弦月", "🌔 盈凸月", "🌕 满月", "🌖 亏凸月", "🌗 下弦月", "🌘 残月"]
            return f"{city} 今晚月相: {random.choice(phases)}"
    elif name == "generate_password":
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(int(args.get("length", 16))))
    elif name == "dream_interpreter":
        dream = args.get("dream_description", "")
        meanings = {"飞行": "向往自由", "水": "情绪流动", "坠落": "对失控的恐惧", "考试": "自我评估的压力", "迷路": "方向感的缺失"}
        for k, v in meanings.items():
            if k in dream:
                return f"梦境解读: 梦见{k}代表{v}。"
        return "梦境解读: 潜意识在与你对话。"
    return f"[未找到工具: {name}]"


# ════════════════════════════════════════════════════════════
#  人格模板
# ════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """你是一位温柔的睡前故事创作师，名字叫「月白」。你的使命是用柔和、有质感的文字，把读者送入安稳的睡眠。

【创作铁律】
R1. 安全感第一：故事中不得出现任何恐怖、紧张、悲伤元素。
R2. 角色限定：主角只能是小动物或自然精灵。
R3. 情节纯度：只有「小小的愿望→温柔的旅程→安定的归来」的弧线。
R4. 五感优先 + 节奏递减 + 句式交替。
R5. 禁止用「突然」「猛地」「哭」「怕」「黑」等字眼。
R6. 字数：首次 350-450 字，续写 250-400 字。
R7. 不要输出推理过程，只输出故事正文。
R8. 以「晚安」或安定意象收尾。

【CoT 五步法】
Step1 主题解构 → Step2 角色设计 → Step3 五感映射 → Step4 叙事弧线 → Step5 结尾意象锁定

请根据用户输入创作一则符合以上规则的睡前故事。"""

CHAT_PROMPT = """你是一位温柔、耐心的AI助手，名字叫「月白」。

【回答规则】
- 回答时优先参考「参考资料」。如果资料中没有相关信息，请说"我目前的知识库中没有相关信息"。
- 你能调用 6 种工具：获取时间、数学计算、掷骰子、月相查询、生成密码、解梦。
- **故事创作**：当用户明确说"讲个故事""睡前故事""想听故事"时，会自动切换到故事模式。"""

ZHIYIN_PROMPT = """你是一位温暖、共情的知音好友，名字叫「月白」。你的风格如月光般温柔包容，善于倾听和回应。

【回答原则】
- 先肯定对方的感受，再给予建议或安慰。
- 营造安全感和信任感，不说教、不评判。
- 结尾常带温暖的祝福或安心的收束。
- 语言柔和但不做作，像朋友夜谈一样自然。"""

SHUMIAN_PROMPT = """你是一位舒眠放松引导师，名字叫「月白」。你的声音充满平静的力量，引导用户放松身心、进入安睡状态。

【引导原则】
- 用平缓、轻柔的语言节奏，多用长短交替的句式。
- 结合呼吸引导、意象冥想和身体放松技巧。
- 避免任何刺激性的画面或声响描述。
- 以"睡眠准备好了"或类似的安定意象收束。"""

PERSONAS = {
    "月白·温柔":   {"emoji": "🌙", "prompt": SYSTEM_PROMPT, "desc": "睡前故事创作"},
    "月白·智能":    {"emoji": "🤖", "prompt": CHAT_PROMPT,    "desc": "通用智能助手"},
    "月白·知心":    {"emoji": "💗", "prompt": ZHIYIN_PROMPT, "desc": "温暖知音陪伴"},
    "月白·舒眠":    {"emoji": "🌿", "prompt": SHUMIAN_PROMPT, "desc": "舒眠放松引导"},
}


# ════════════════════════════════════════════════════════════
#  内存会话管理(简化版)
# ════════════════════════════════════════════════════════════
def get_or_create_user(name: str) -> str:
    if name not in _users:
        _users[name] = f"u_{uuid.uuid4().hex[:8]}"
    return _users[name]


def create_session(user_id: str, title: str = "新会话") -> str:
    sid = f"s_{uuid.uuid4().hex[:8]}"
    _sessions[sid] = {"user_id": user_id, "title": title, "messages": [], "updated_at": time.time()}
    return sid


def list_sessions(user_id: str):
    return [
        {"id": sid, "title": s["title"], "created_at": s["updated_at"],
         "updated_at": s["updated_at"], "msg_count": len(s["messages"])}
        for sid, s in _sessions.items() if s["user_id"] == user_id
    ]


def delete_session(sid: str):
    _sessions.pop(sid, None)


def load_history(session_id: str, limit: int = 20):
    s = _sessions.get(session_id)
    if not s:
        return []
    return s["messages"][-limit:]


def save_msg(session_id: str, role: str, content: str):
    s = _sessions.get(session_id)
    if not s:
        return
    s["messages"].append({"role": role, "content": content})
    s["updated_at"] = time.time()


# ════════════════════════════════════════════════════════════
#  路由
# ════════════════════════════════════════════════════════════
@app.route("/")
def index():
    try:
        return render_template("index.html")
    except Exception as e:
        return json.dumps({"app": "月白 AI Agent", "status": "ok", "platform": "serverless", "debug": str(e)}), 200, {"Content-Type": "application/json"}


@app.route("/healthz")
def healthz():
    return json.dumps({"status": "ok", "model": DEEPSEEK_MODEL, "embed_model": OPENAI_EMBED_MODEL})


@app.route("/api/personas")
def get_personas():
    return json.dumps([{"key": k, "name": k, "emoji": v["emoji"], "desc": v["desc"]}
                       for k, v in PERSONAS.items()], ensure_ascii=False)


@app.route("/api/session", methods=["POST"])
def create_session_route():
    uid = get_or_create_user("web_user")
    sid = create_session(uid, f"会话 {datetime.now().strftime('%m/%d %H:%M')}")
    return json.dumps({"session_id": sid, "user_id": uid}, ensure_ascii=False)


@app.route("/api/sessions")
def list_sessions_route():
    return json.dumps({"sessions": list_sessions(get_or_create_user("web_user"))}, ensure_ascii=False)


@app.route("/api/session/<sid>/messages", methods=["GET"])
def get_session_messages(sid):
    return json.dumps({"session_id": sid, "messages": load_history(sid, 100)}, ensure_ascii=False)


@app.route("/api/session/<sid>", methods=["DELETE"])
def delete_session_route(sid):
    delete_session(sid)
    return json.dumps({"status": "ok"})


@app.route("/api/kb/search", methods=["POST"])
def kb_search():
    query = request.get_json(force=True).get("query", "")
    if not query:
        return json.dumps({"docs": []})
    docs, sources, scores = hybrid_search(query, top_k=3)
    results = [{"text": d, "source": s, "score": sc} for d, s, sc in zip(docs, sources, scores)]
    return json.dumps({"query": query, "results": results, "count": len(results)}, ensure_ascii=False)


@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json(force=True)
        msg = data.get("message", "").strip()
        sid = data.get("session_id", uuid.uuid4().hex)
        persona = data.get("persona", "月白·智能")
        if not msg:
            return json.dumps({"error": "消息不能为空"}), 400
        # 检查 API Key 是否配置
        if not DEEPSEEK_API_KEY:
            return json.dumps({"error": "DEEPSEEK_API_KEY 环境变量未设置,请到 Railway Variables 配置"}), 503
        return Response(
            stream_with_context(generate_stream(sid, msg, persona)),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    except Exception as e:
        print(f"[/chat 错误] {e}")
        return json.dumps({"error": f"聊天服务异常: {str(e)}"}), 500


# ════════════════════════════════════════════════════════════
#  CrewAI 4 Agent 流水线(用 4 次 LLM 调用模拟,无 CrewAI 依赖)
# ════════════════════════════════════════════════════════════
def crewai_story_pipeline(user_prompt: str) -> dict:
    """4 Agent 流水线:策划→资料→创作→审核"""
    # 1. 选题策划
    plan = llm_client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "你是儿童故事选题策划师。"},
            {"role": "user", "content": f"为「{user_prompt}」设计睡前故事:\n【主题】\n【主角】\n【场景】\n【情节线】"}
        ],
        temperature=0.7, max_tokens=400,
    ).choices[0].message.content

    # 2. 资料检索
    rag_docs, _, _ = hybrid_search(plan, top_k=2)
    refs = "\n---\n".join(rag_docs) if rag_docs else "(无)"

    # 3. 故事创作
    story = llm_client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"方案:\n{plan}\n参考:\n{refs}\n需求:{user_prompt}\n请写 350-450 字故事正文,不要标题。"}
        ],
        temperature=0.8, max_tokens=800,
    ).choices[0].message.content

    # 4. 质量审核
    review = llm_client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "你是睡前故事审核员,对照 8 条铁律(R1-R8)审核。"},
            {"role": "user", "content": f"审核以下故事,给出 R1-R8 评分(✅/❌)和最终优化版:\n{story}"}
        ],
        temperature=0.3, max_tokens=1000,
    ).choices[0].message.content

    return {"plan": plan, "story": story, "review": review}


@app.route("/api/crew", methods=["POST"])
def crew_endpoint():
    data = request.get_json(force=True)
    prompt = data.get("message", "").strip()
    if not prompt:
        return json.dumps({"error": "消息不能为空"}), 400
    result = crewai_story_pipeline(prompt)
    return json.dumps(result, ensure_ascii=False)


# ════════════════════════════════════════════════════════════
#  SSE 流式核心
# ════════════════════════════════════════════════════════════
def generate_stream(session_id: str, user_message: str, persona_key: str):
    persona = PERSONAS.get(persona_key, PERSONAS["学小助·默认"])
    system_prompt = persona["prompt"]
    lower_msg = user_message.lower().strip()

    # 确保 session 存在
    if session_id not in _sessions:
        uid = get_or_create_user("web_user")
        _sessions[session_id] = {"user_id": uid, "title": "新会话", "messages": [], "updated_at": time.time()}

    # 故事意图识别 — 仅当用户明确要求讲故事时才进故事模式
    # 与当前人格无关（即使用户选了"月白·温柔"，不说"讲故事"也不会自动切）
    STORY_WORDS = ["睡前故事", "讲个故事", "讲一个故事", "想听故事", "听个故事",
                   "写个故事", "写一个故事", "写个童话", "来一个故事", "给我讲",
                   "念个故事", "编个故事", "编一个故事", "来个童话", "讲童话",
                   "写童话", "编童话", "讲故事", "讲寓言", "写寓言", "哄睡", "哄我"]
    CONTINUE_WORDS = ["继续", "继续讲", "接着讲", "然后呢", "还有呢", "继续讲",
                      "接着说", "再讲一点", "还有吗", "之后呢", "接下来呢"]
    wants_story = (
        any(kw in user_message for kw in STORY_WORDS)
        or user_message.strip() in CONTINUE_WORDS
    )

    if wants_story:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        msgs.extend(load_history(session_id))
        msgs.append({"role": "user", "content": user_message})
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': '🌙 故事模式（自动）'}, ensure_ascii=False)}\n\n"
        yield from _llm_stream(msgs, session_id, user_message)
        return

    # 普通对话
    msgs = [{"role": "system", "content": system_prompt}]
    msgs.extend(load_history(session_id))

    # RAG 检索
    rag_docs, rag_sources, rag_scores = [], [], []
    try:
        rag_docs, rag_sources, rag_scores = hybrid_search(user_message, top_k=3)
        if rag_docs:
            yield f"data: {json.dumps({'type': 'rag_context', 'docs': rag_docs, 'sources': rag_sources, 'scores': rag_scores}, ensure_ascii=False)}\n\n"
    except Exception as e:
        print(f"  [RAG 错误] {e}")

    # 工具路由
    TIME_WORDS_FULL = ["现在几点", "几点了", "什么时间", "现在时间", "当前时间",
                       "目前时间", "现在是什么时候", "现在是什么时候"]
    if any(kw in user_message for kw in TIME_WORDS_FULL) or \
       (("几点" in user_message or "时间" in user_message) and "现在" in user_message and len(user_message) < 15) or \
       (lower_msg in ["几点了", "现在几点", "现在几点了", "现在时间", "今天是几号", "今天日期", "今天星期几", "今天周几"]):
        t = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': f'🕐 get_current_time → {t}'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': f'现在是 **{t}**。'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        save_msg(session_id, "user", user_message)
        save_msg(session_id, "assistant", f"现在是 {t}。")
        return

    if any(kw in lower_msg for kw in ["骰子", "掷", "roll"]):
        c = 3 if "三" in lower_msg else (2 if "两" in lower_msg or "二" in lower_msg else 1)
        s = next((int(x) for x in lower_msg.split() if x.isdigit()), 6)
        r = [random.randint(1, s) for _ in range(c)]
        t = sum(r)
        reply = f"🎲 掷了 {c} 个 {s} 面骰子：**{r}**，总和 **{t}**。"
        if t >= s * c * 0.8: reply += " 大成功！🎉"
        elif t <= c * 2: reply += " 运气不太好…"
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': '🎲 roll_dice'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': reply}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        save_msg(session_id, "user", user_message)
        save_msg(session_id, "assistant", reply)
        return

    if any(kw in lower_msg for kw in ["密码", "password"]) or ("生成" in lower_msg and any(p in lower_msg for p in ["密码", "口令"])):
        ln = next((int(x) for x in lower_msg.split() if x.isdigit()), 16)
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        pwd = ''.join(random.choice(chars) for _ in range(ln))
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': f'🔑 generate_password(length={ln})'}, ensure_ascii=False)}\n\n"
        _content = f'🔑 已生成 **{ln}** 位密码：\n\n`{pwd}`'
        yield f"data: {json.dumps({'type': 'chunk', 'content': _content}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        save_msg(session_id, "user", user_message)
        save_msg(session_id, "assistant", f"密码: {pwd}")
        return

    if any(kw in lower_msg for kw in ["月相", "月亮", "moon"]):
        city = next((c for c in ["北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆"] if c in lower_msg), "北京")
        phase = execute_tool("get_moon_phase", {"city": city})
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': '🌙 get_moon_phase'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': phase}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        save_msg(session_id, "user", user_message)
        save_msg(session_id, "assistant", phase)
        return

    if any(kw in lower_msg for kw in ["梦见", "梦到", "做梦", "解梦", "dream"]):
        result = execute_tool("dream_interpreter", {"dream_description": user_message})
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': '🔮 dream_interpreter'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': result}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        save_msg(session_id, "user", user_message)
        save_msg(session_id, "assistant", result)
        return

    # LLM 流式
    ref = ""
    if rag_docs:
        ref_parts = ["\n\n📚 以下资料供参考(按相关性排序):"]
        for i, (d, s, sc) in enumerate(zip(rag_docs, rag_sources, rag_scores)):
            ref_parts.append(f"\n---\n[来源{i+1}] {s} | 分数: {sc}\n{d[:300]}")
        ref = "".join(ref_parts)
    msgs.append({"role": "user", "content": f"{user_message}{ref}"})
    yield from _llm_stream(msgs, session_id, user_message)


def _llm_stream(messages, session_id, user_message):
    try:
        stream = llm_client.chat.completions.create(
            model=DEEPSEEK_MODEL, messages=messages, stream=True,
            temperature=0.80, max_tokens=1024)
        save_msg(session_id, "user", user_message)
        full = []
        for chunk in stream:
            d = chunk.choices[0].delta.content
            if d:
                full.append(d)
                yield f"data: {json.dumps({'type': 'chunk', 'content': d}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        save_msg(session_id, "assistant", "".join(full))
    except Exception as e:
        yield f"data: {json.dumps({'type': 'chunk', 'content': f'抱歉,遇到了错误:{e}'}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"


# ════════════════════════════════════════════════════════════
#  本地开发
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("╔══════════════════════════════════════════════╗")
    print("║   月白 AI Agent · Serverless 版            ║")
    print("║   2325102015 黄凯豪                          ║")
    print("╚══════════════════════════════════════════════╝")
    print(f"  🧠 LLM: {DEEPSEEK_MODEL}")
    print(f"  📐 Embeddings: {OPENAI_EMBED_MODEL}")
    print(f"  📚 KB: {len(_vector_store)} 段")
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
