"""
月白 AI Agent — Flask Web 应用（单文件版）
═══════════════════════════════════════════════════════
集成：LlamaIndex RAG + SQLite 会话管理 + 6 工具 + 4 人格 + SSE 流式
全部代码在同一个文件，无需其他 .py 依赖。

学号：2325102015  姓名：黄凯豪
"""

import json, os, sys, uuid, time, random, string, sqlite3, urllib.request
from datetime import datetime
from flask import Flask, render_template, request, Response, stream_with_context
from flask_cors import CORS
from openai import OpenAI

# ════════════════════════════════════════════════════════════
#  LangSmith 监控配置（必须在其他导入之前设置环境变量）
# ════════════════════════════════════════════════════════════
import langsmith_config  # noqa: F401  设置 LANGSMITH_* 环境变量
from langsmith import traceable
from langsmith.wrappers import wrap_openai

# ════════════════════════════════════════════════════════════
#  LLM 配置（从环境变量读取，不在代码中硬编码密钥）
# ════════════════════════════════════════════════════════════
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
if not API_KEY:
    raise RuntimeError("❌ 未设置 DEEPSEEK_API_KEY 环境变量！请在 Railway Variables 中配置。")
# 用 wrap_openai 包装 OpenAI 客户端 —— 所有 chat.completions 调用会自动生成 LangSmith Trace
llm_client = wrap_openai(OpenAI(api_key=API_KEY, base_url=BASE_URL))

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_CHROMA_DIR = os.path.join(_PROJECT_DIR, "chroma_db")
_MODEL_DIR = os.path.join(_PROJECT_DIR, "bge_local")

app = Flask(__name__)
CORS(app)


# ════════════════════════════════════════════════════════════
#  SQLite 会话管理（内联自 session_manager.py）
# ════════════════════════════════════════════════════════════
DB_PATH = os.path.join(_PROJECT_DIR, "chat_history.db")

def init_database():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            title TEXT NOT NULL DEFAULT '新会话',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS message_store (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def create_user(name):
    conn = sqlite3.connect(DB_PATH)
    uid = f"u_{uuid.uuid4().hex[:8]}"
    conn.execute("INSERT INTO users (id, name) VALUES (?, ?)", (uid, name))
    conn.commit()
    conn.close()
    return uid

def get_or_create_user(name):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()
    conn.close()
    return row[0] if row else create_user(name)

def create_session(user_id, title="新会话"):
    conn = sqlite3.connect(DB_PATH)
    sid = f"s_{uuid.uuid4().hex[:8]}"
    conn.execute("INSERT INTO sessions (id, user_id, title) VALUES (?, ?, ?)", (sid, user_id, title))
    conn.commit()
    conn.close()
    return sid

def list_sessions(user_id):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT s.id, s.title, s.created_at, s.updated_at,
               (SELECT COUNT(*) FROM message_store m WHERE m.session_id = s.id) AS msg_count
        FROM sessions s WHERE s.user_id = ? ORDER BY s.updated_at DESC
    """, (user_id,)).fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3], "msg_count": r[4]} for r in rows]

def delete_session(sid):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM message_store WHERE session_id=?", (sid,))
    conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
    conn.commit()
    conn.close()

def get_sql_history(session_id):
    """返回 SQLChatMessageHistory 实例，或 None"""
    try:
        from langchain_community.chat_message_histories import SQLChatMessageHistory
        return SQLChatMessageHistory(session_id=session_id, connection=f"sqlite:///{DB_PATH}", table_name="message_store")
    except Exception:
        return None

def save_messages(sql_history, user_msg, assistant_msg):
    if sql_history is None:
        return
    try:
        from langchain_core.messages import HumanMessage, AIMessage
        sql_history.add_message(HumanMessage(content=user_msg))
        sql_history.add_message(AIMessage(content=assistant_msg))
    except Exception as e:
        print(f"  [保存消息失败] {e}")

def load_history_messages(sql_history):
    """从 SQLite 加载最近 20 条消息"""
    if sql_history is None:
        return []
    msgs = []
    for msg in sql_history.messages[-20:]:
        role = "assistant" if msg.type in ("ai", "assistant") else "user" if msg.type == "human" else "system"
        msgs.append({"role": role, "content": msg.content})
    return msgs


# ════════════════════════════════════════════════════════════
#  增强型 RAG 引擎：Hybrid Search + Rerank + Query Rewrite
# ════════════════════════════════════════════════════════════
_rag_instance = None
_kb_collection = None
_kb_bm25 = None
_kb_tokenized = None
_kb_reranker = None
_kb_ready = False      # 标记 KB 是否已初始化（非阻塞）
_kb_embed_model = None  # BGE 本地嵌入模型，用于查询编码

def _get_embedding(text):
    """使用本地 BGE 模型计算文本嵌入向量，避免 ChromaDB 下载 ONNX"""
    global _kb_embed_model
    if _kb_embed_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _kb_embed_model = SentenceTransformer(str(_MODEL_DIR))
        except Exception as e:
            print(f"  [嵌入模型加载失败] {e}")
            return None
    try:
        vec = _kb_embed_model.encode([text], normalize_embeddings=True)[0].tolist()
        return vec
    except Exception as e:
        print(f"  [编码失败] {e}")
        return None

# 配置参数
RERANK_RECALL_K = 10          # 向量+BM25 各取 Top-N 做 RRF 融合
RERANK_TOP_K = 3              # Rerank 后取前 K 条
RRF_K = 60                    # RRF 融合常数
KB_SIM_THRESHOLD = 0.25       # 最低余弦相似度阈值

# 检查 rerank 和 bm25 依赖
_RERANK_AVAILABLE = False
_BM25_AVAILABLE = False
try:
    from FlagEmbedding import FlagReranker
    _RERANK_AVAILABLE = True
except ImportError:
    pass
try:
    from rank_bm25 import BM25Okapi
    _BM25_AVAILABLE = True
except ImportError:
    pass

def _ensure_kb():
    """全局懒加载 ChromaDB 连接 + BM25 索引 + Rerank 模型"""
    global _kb_collection, _kb_bm25, _kb_tokenized, _kb_reranker, _kb_ready
    if _kb_collection is not None:
        return
    import chromadb
    from chromadb.config import Settings
    client = chromadb.PersistentClient(path=_CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
    _kb_collection = client.get_collection("my_kb")
    _kb_ready = True  # 基础连接就绪，向量检索可用

    # 构建 BM25 索引（轻量，快速）
    if _BM25_AVAILABLE:
        import threading
        def _build_bm25():
            global _kb_bm25, _kb_tokenized
            if _kb_bm25 is not None:
                return
            try:
                all_data = _kb_collection.get(include=["documents"])
                all_docs = all_data.get("documents", [])
                if all_docs:
                    import jieba
                    _kb_tokenized = [list(jieba.cut(d)) for d in all_docs]
                    _kb_bm25 = BM25Okapi(_kb_tokenized)
            except Exception as e:
                print(f"  [BM25 构建失败] {e}")
        t = threading.Thread(target=_build_bm25, daemon=True)
        t.start()

    # 加载 Rerank 模型（耗时，后台异步加载）
    if _RERANK_AVAILABLE:
        import threading
        def _load_reranker():
            global _kb_reranker
            if _kb_reranker is not None:
                return
            try:
                _kb_reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=False)
            except Exception as e:
                print(f"  [Rerank 加载失败] {e}")
                _kb_reranker = None
        t = threading.Thread(target=_load_reranker, daemon=True)
        t.start()

def bm25_search(query, top_k=10):
    """BM25 关键词召回"""
    if _kb_bm25 is None or not _kb_collection:
        return [], [], []
    import jieba
    tokens = list(jieba.cut(query))
    scores = _kb_bm25.get_scores(tokens)
    all_data = _kb_collection.get(include=["documents", "metadatas"])
    all_ids = all_data.get("ids", [])
    all_docs = all_data.get("documents", [])
    all_metas = all_data.get("metadatas", [])
    scored = sorted(
        [(i, s) for i, s in enumerate(scores) if s > 0],
        key=lambda x: x[1], reverse=True,
    )[:top_k]
    return (
        [all_ids[i] for i, _ in scored],
        [all_docs[i] for i, _ in scored],
        [all_metas[i] for i, _ in scored],
    )

@traceable(name="RAG_Hybrid检索", run_type="retriever")
def hybrid_search(question, top_k=RERANK_TOP_K):
    """混合检索：向量召回 + BM25 + RRF 融合 + 可选 Rerank"""
    _ensure_kb()
    total = _kb_collection.count() or 0
    if total == 0:
        return [], [], []

    # ── 1) 向量召回 Top-${RERANK_RECALL_K} ──
    vec_topk = min(RERANK_RECALL_K, total)
    query_emb = _get_embedding(question)
    if query_emb is None:
        # 降级：使用 ChromaDB 内置 embedding（会下载 ONNX，较慢）
        try:
            vec_res = _kb_collection.query(
                query_texts=[question],
                n_results=vec_topk,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            print(f"  [向量检索失败] {e}")
            return [], [], []
    else:
        try:
            vec_res = _kb_collection.query(
                query_embeddings=[query_emb],
                n_results=vec_topk,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            print(f"  [向量检索失败] {e}")
            return [], [], []
    vec_ids = vec_res.get("ids", [[]])[0]
    vec_docs = vec_res.get("documents", [[]])[0]
    vec_metas = vec_res.get("metadatas", [[]])[0]
    vec_dists = vec_res.get("distances", [[]])[0]
    # ChromaDB cosine distance → 余弦相似度
    vec_sims = {cid: max(0.0, 1.0 - float(d)) for cid, d in zip(vec_ids, vec_dists)}

    # ── 2) BM25 关键词召回 ──
    bm_ids, bm_docs, bm_metas = bm25_search(question, top_k=RERANK_RECALL_K)

    # ── 3) RRF 融合 ──
    rrf = {}
    for rank, cid in enumerate(vec_ids):
        e = rrf.setdefault(cid, {"rrf_score": 0.0, "doc": vec_docs[rank],
                                  "meta": vec_metas[rank], "sim": vec_sims.get(cid, 0.0)})
        e["rrf_score"] += 1.0 / (rank + 1 + RRF_K)
    for rank, cid in enumerate(bm_ids):
        e = rrf.setdefault(cid, {"rrf_score": 0.0, "doc": bm_docs[rank],
                                  "meta": bm_metas[rank], "sim": 0.0})
        e["rrf_score"] += 1.0 / (rank + 1 + RRF_K)

    fused = sorted(rrf.values(), key=lambda v: v["rrf_score"], reverse=True)[:RERANK_RECALL_K]
    fused_docs = [v["doc"] for v in fused]
    fused_metas = [v["meta"] for v in fused]
    fused_rrf = [v["rrf_score"] for v in fused]
    fused_sims = [v["sim"] for v in fused]

    # ── 4) Rerank 精排 ──
    top_docs, top_metas, top_score_strs = [], [], []
    if _RERANK_AVAILABLE and _kb_reranker is not None and fused_docs:
        pairs = [[question, d] for d in fused_docs]
        try:
            rerank_scores = [float(s) for s in _kb_reranker.compute_score(pairs, batch_size=2)]
        except Exception:
            rerank_scores = None
        if rerank_scores is not None:
            ranked = sorted(
                zip(fused_docs, fused_metas, rerank_scores, fused_rrf, fused_sims),
                key=lambda x: x[2], reverse=True,
            )[:top_k]
            top_docs = [r[0] for r in ranked]
            top_metas = [r[1] for r in ranked]
            top_score_strs = [f"重排={r[2]:.3f} | RRF={r[3]:.0f} | 余弦={r[4]:.3f}" for r in ranked]
            if ranked and ranked[0][2] < 0.1:
                return [], [], []
        else:
            for v in fused[:top_k]:
                top_docs.append(v["doc"])
                top_metas.append(v["meta"])
                top_score_strs.append(f"RRF={v['rrf_score']:.0f} | 余弦={v['sim']:.3f}")
    else:
        for v in fused[:top_k]:
            top_docs.append(v["doc"])
            top_metas.append(v["meta"])
            top_score_strs.append(f"RRF={v['rrf_score']:.0f} | 余弦={v['sim']:.3f}")
        if fused and fused[0]["sim"] < KB_SIM_THRESHOLD:
            return [], [], []

    if not top_docs:
        return [], [], []

    # 拼来源标签
    sources = []
    for m in top_metas:
        if m and "source" in m and "chunk_index" in m:
            sources.append(f"{m['source']} 第{m['chunk_index']}段")
        elif m and "source" in m:
            sources.append(str(m['source']))
        else:
            sources.append("(未知)")
    return top_docs, sources, top_score_strs


@traceable(name="RAG_查询改写", run_type="chain")
def rewrite_query(question):
    """调用 LLM 对用户查询做改写，提升检索命中率"""
    if len(question.strip()) <= 4:
        return question
    try:
        resp = llm_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{
                "role": "system",
                "content": "你是一个检索查询改写助手。将用户的自然语言问题改写成一段简洁、适合向量检索的查询文本。"
                           "只输出改写后的文本，不要多余内容。如果问题很短或已经是关键词形式，直接返回原句。"
            }, {
                "role": "user",
                "content": f"改写以下查询，使其更适合知识库检索：{question}"
            }],
            temperature=0.1,
            max_tokens=128,
        )
        rewritten = resp.choices[0].message.content.strip()
        return rewritten if rewritten else question
    except Exception as e:
        print(f"  [查询改写失败] {e}")
        return question


def get_rag():
    """保留兼容旧接口的全局单例"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = hybrid_search  # 函数引用，不是 LlamaindexRAG 实例
    return _rag_instance


# ════════════════════════════════════════════════════════════
#  工具函数
# ════════════════════════════════════════════════════════════
@traceable(name="工具调用", run_type="tool")
def execute_tool(name, args):
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
            with urllib.request.urlopen(f"https://wttr.in/{city}?format=%m", timeout=5) as r:
                return f"{city} 今晚月相: {r.read().decode('utf-8').strip()}"
        except Exception:
            phases = ["🌑 新月","🌒 蛾眉月","🌓 上弦月","🌔 盈凸月","🌕 满月","🌖 亏凸月","🌗 下弦月","🌘 残月"]
            return f"{city} 今晚月相: {random.choice(phases)}"
    elif name == "generate_password":
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        return ''.join(random.choice(chars) for _ in range(int(args.get("length", 16))))
    elif name == "dream_interpreter":
        dream = args.get("dream_description", "")
        meanings = {"飞行": "向往自由","水": "情绪流动","坠落": "对失控的恐惧","考试": "自我评估的压力","迷路": "方向感的缺失"}
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

PERSONAS = {
    "月白·温柔":   {"emoji":"🌙", "prompt": SYSTEM_PROMPT, "desc": "睡前故事创作"},
    "学小助·默认":  {"emoji":"🎓", "prompt": CHAT_PROMPT, "desc": "友好校园助手"},
    "铁血老哥":     {"emoji":"👨‍🏫", "prompt": f"{CHAT_PROMPT}\n\n但你现在是一个严厉的督学导师。说话直接，批评后必给建议。", "desc": "严厉督学导师"},
    "温柔守护者":   {"emoji":"💚", "prompt": f"{CHAT_PROMPT}\n\n但你现在是一个温柔、共情的心理陪伴者。先肯定感受再引导。", "desc": "心理陪伴型"},
}


# ════════════════════════════════════════════════════════════
#  API 路由
# ════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/personas")
def get_personas():
    return json.dumps([{"key":k, "name":k, "emoji":v["emoji"], "desc":v["desc"]} for k,v in PERSONAS.items()], ensure_ascii=False)

@app.route("/api/session", methods=["POST"])
def create_session_route():
    init_database()
    uid = get_or_create_user("web_user")
    sid = create_session(uid, f"会话 {datetime.now().strftime('%m/%d %H:%M')}")
    return json.dumps({"session_id": sid, "user_id": uid}, ensure_ascii=False)

@app.route("/api/sessions")
def list_sessions_route():
    init_database()
    return json.dumps({"sessions": list_sessions(get_or_create_user("web_user"))}, ensure_ascii=False)

@app.route("/api/session/<sid>/messages", methods=["GET"])
def get_session_messages(sid):
    """查看指定会话的历史消息"""
    from langchain_core.messages import HumanMessage, AIMessage
    from langchain_community.chat_message_histories import SQLChatMessageHistory as _SQL
    try:
        hist = _SQL(session_id=sid, connection=f"sqlite:///{DB_PATH}", table_name="message_store")
        msgs = []
        for m in hist.messages:
            role = "assistant" if m.type in ("ai", "assistant") else "user"
            msgs.append({"role": role, "content": m.content})
        return json.dumps({"session_id": sid, "messages": msgs}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"session_id": sid, "messages": [], "error": str(e)})

@app.route("/api/session/<sid>", methods=["DELETE"])
def delete_session_route(sid):
    delete_session(sid)
    return json.dumps({"status": "ok"})

@app.route("/api/kb/search", methods=["POST"])
def kb_search():
    query = request.get_json(force=True).get("query", "")
    if not query:
        return json.dumps({"docs": []})
    # 使用增强的混合检索（API 路由不调用 LLM 改写，避免超时）
    docs, sources, scores = hybrid_search(query, top_k=3)
    results = [{"text": d, "source": s, "score": sc} for d, s, sc in zip(docs, sources, scores)]
    return json.dumps({"query": query, "results": results, "count": len(results)}, ensure_ascii=False)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True)
    msg = data.get("message", "").strip()
    sid = data.get("session_id", uuid.uuid4().hex)
    persona = data.get("persona", "月白·温柔")
    if not msg:
        return json.dumps({"error": "消息不能为空"}), 400
    return Response(
        stream_with_context(generate_stream(sid, msg, persona)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ════════════════════════════════════════════════════════════
#  SSE 流式生成核心
# ════════════════════════════════════════════════════════════

@traceable(name="月白_对话主流程", run_type="chain")
def generate_stream(session_id, user_message, persona_key):
    persona = PERSONAS.get(persona_key, PERSONAS["学小助·默认"])
    system_prompt = persona["prompt"]
    lower_msg = user_message.lower().strip()
    init_database()
    history = get_sql_history(session_id)

    # ── 0. 故事意图识别（改进：支持"继续讲""接着讲""还有呢"等） ──
    STORY_WORDS = ["睡前故事","睡前小故事","讲个故事","讲一个故事","讲个睡前故事",
        "讲一个睡前故事","想听故事","听个故事","写个故事","写一个故事",
        "写个童话","写一个童话","来一个故事","给我讲","念个故事",
        "编个故事","编一个故事","来个童话","讲童话","写童话","编童话",
        "讲寓言","写寓言","哄睡","哄我","讲故事"]
    CONTINUE_WORDS = ["继续","继续讲","接着讲","然后呢","还有呢","继续讲",
        "接着说","再讲一点","还有吗","之后呢","接下来呢"]
    wants_story = (
        any(kw in user_message for kw in STORY_WORDS)
        or user_message.strip() in CONTINUE_WORDS
        or any(("故事" in user_message or "童话" in user_message) and v in user_message for v in ["讲","听","写","生成","编","念","来","给我"])
        or ("睡前" in user_message and any(n in user_message for n in ["故事","童话","寓言","神话","哄"]))
    )

    if wants_story:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        msgs.extend(load_history_messages(history))
        msgs.append({"role": "user", "content": user_message})
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': '🌙 故事模式（自动）'})}\n\n"
        yield from _llm_stream(msgs, history, user_message)
        return

    # ── 1. 加载历史 ──
    msgs = [{"role": "system", "content": system_prompt}]
    msgs.extend(load_history_messages(history))

    # ── 2. RAG 检索（增强版：混合检索 + 来源 + 分数） ──
    rag_docs, rag_sources, rag_scores = [], [], []
    try:
        rewritten = rewrite_query(user_message)
        rag_docs, rag_sources, rag_scores = hybrid_search(rewritten, top_k=3)
        if rag_docs:
            yield f"data: {json.dumps({'type': 'rag_context', 'docs': rag_docs, 'sources': rag_sources, 'scores': rag_scores})}\n\n"
    except Exception as e:
        print(f"  [RAG 错误] {e}")

    # ── 3. 工具路由（改进：带上下文感知，减少误触发） ──
    # 时间查询：必须是直接问时间/日期，而不是句中包含"今天"等词
    TIME_WORDS_FULL = ["现在几点","几点了","什么时间","现在时间","当前时间","目前时间","现在是什么时候"]
    if any(kw in user_message for kw in TIME_WORDS_FULL) or \
       (("几点" in user_message or "时间" in user_message) and "现在" in user_message and len(user_message) < 15) or \
       (lower_msg in ["几点了", "现在几点", "现在几点了", "现在时间", "今天是几号", "今天日期", "今天星期几", "今天周几"]):
        t = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': f'🕐 get_current_time → {t}'})}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': f'现在是 **{t}**。'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        save_messages(history, user_message, f"现在是 {t}。"); return

    if any(kw in lower_msg for kw in ["骰子","掷","roll"]):
        c = 3 if "三" in lower_msg else (2 if "两" in lower_msg or "二" in lower_msg else 1)
        s = next((int(x) for x in lower_msg.split() if x.isdigit()), 6)
        r = [random.randint(1, s) for _ in range(c)]
        t = sum(r)
        reply = f"🎲 掷了 {c} 个 {s} 面骰子：**{r}**，总和 **{t}**。"
        if t >= s*c*0.8: reply += " 大成功！🎉"
        elif t <= c*2: reply += " 运气不太好…"
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': f'🎲 roll_dice'})}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': reply})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        save_messages(history, user_message, reply); return

    if any(kw in lower_msg for kw in ["密码","password"]) or ("生成" in lower_msg and any(p in lower_msg for p in ["密码","口令"])):
        ln = next((int(x) for x in lower_msg.split() if x.isdigit()), 16)
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        pwd = ''.join(random.choice(chars) for _ in range(ln))
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': f'🔑 generate_password(length={ln})'})}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': f'🔑 已生成 **{ln}** 位密码：\n\n`{pwd}`'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        save_messages(history, user_message, f"密码: {pwd}"); return

    if any(kw in lower_msg for kw in ["月相","月亮","moon"]):
        city = next((c for c in ["北京","上海","广州","深圳","杭州","成都","武汉","南京","西安","重庆"] if c in lower_msg), "北京")
        phase = execute_tool("get_moon_phase", {"city": city})
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': f'🌙 get_moon_phase'})}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': phase})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        save_messages(history, user_message, phase); return

    if any(kw in lower_msg for kw in ["梦见","梦到","做梦","解梦","dream"]):
        result = execute_tool("dream_interpreter", {"dream_description": user_message})
        yield f"data: {json.dumps({'type': 'tool_call', 'tool': '🔮 dream_interpreter'})}\n\n"
        yield f"data: {json.dumps({'type': 'chunk', 'content': result})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        save_messages(history, user_message, result); return

    # ── 4. LLM 流式，附带结构化参考资料 ──
    ref = ""
    if rag_docs:
        ref_parts = ["\n\n📚 以下资料供参考（按相关性排序）："]
        for i, (d, s, sc) in enumerate(zip(rag_docs, rag_sources, rag_scores)):
            ref_parts.append(f"\n---\n[来源{i+1}] {s} | 分数: {sc}\n{d[:300]}")
        ref = "".join(ref_parts)
    msgs.append({"role": "user", "content": f"{user_message}{ref}"})
    yield from _llm_stream(msgs, history, user_message)


@traceable(name="LLM_流式生成", run_type="llm")
def _llm_stream(messages, sql_history, user_message):
    try:
        stream = llm_client.chat.completions.create(
            model=MODEL_NAME, messages=messages, stream=True,
            temperature=0.80, max_tokens=1024)
        full = []
        for chunk in stream:
            d = chunk.choices[0].delta.content
            if d:
                full.append(d)
                yield f"data: {json.dumps({'type': 'chunk', 'content': d})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        save_messages(sql_history, user_message, "".join(full))
    except Exception as e:
        yield f"data: {json.dumps({'type': 'chunk', 'content': f'抱歉，遇到了错误：{e}'})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ════════════════════════════════════════════════════════════
#  启动
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # 预热 KB 和嵌入模型，降低首次请求延迟
    try:
        import threading
        threading.Thread(target=_ensure_kb, daemon=True).start()
        threading.Thread(target=_get_embedding, args=("预热",), daemon=True).start()
    except Exception:
        pass
    
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   月白 AI Agent · 单文件版                 ║")
    print("║   2325102015 黄凯豪                          ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print(f"  🌐 http://localhost:5050")
    print(f"  🧠 LLM: DeepSeek ({MODEL_NAME})")
    print(f"  📚 RAG: LlamaIndex + ChromaDB")
    print(f"  🎭 人格: {len(PERSONAS)} 种")
    print(f"  🛠️  工具: 6 个")
    print(f"  🗄️  记忆: SQLite 持久化")
    print(f"  📁 仅依赖: app.py + templates/ + chroma_db/ + bge_local/")
    print()
    app.run(host="127.0.0.1", port=5050, debug=False, threaded=True)
