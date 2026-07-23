"""
CrewAI 多 Agent 任务链 — 月白睡前故事创作系统
═══════════════════════════════════════════════════════════
定义 4 个 Agent 角色，构建串行任务链：
  1. 选题策划师  → 分析主题、设计角色与场景
  2. 资料搜集员  → 检索知识库，提供参考素材
  3. 故事创作师  → 撰写符合规则的睡前故事
  4. 质量审核员  → 对照创作铁律审核并优化

学号：2325102015  姓名：黄凯豪
"""

import os
import sys
import json
import chromadb
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool

# ════════════════════════════════════════════════════════════
#  LLM 配置 — DeepSeek (OpenAI 兼容接口)
# ════════════════════════════════════════════════════════════
API_KEY = "sk-8105f2a68d4e4b76b6c3664a53119276"
BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

deepseek_llm = LLM(
    model=f"openai/{MODEL_NAME}",
    base_url=BASE_URL,
    api_key=API_KEY,
    temperature=0.8,
    max_tokens=2048,
)

_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_CHROMA_DIR = os.path.join(_PROJECT_DIR, "chroma_db")


# ════════════════════════════════════════════════════════════
#  自定义工具：知识库检索
# ════════════════════════════════════════════════════════════
@tool("kb_search_tool")
def kb_search_tool(query: str) -> str:
    """Search the local knowledge base for documents related to the query. Input search keywords, returns the most relevant document content. 在本地知识库中检索与查询相关的文档片段。"""
    try:
        from chromadb.config import Settings
        client = chromadb.PersistentClient(
            path=_CHROMA_DIR,
            settings=Settings(anonymized_telemetry=False)
        )
        collection = client.get_collection("my_kb")
        results = collection.query(
            query_texts=[query],
            n_results=3,
            include=["documents", "metadatas"]
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        if not docs:
            return "知识库中未找到相关内容。"
        output_parts = []
        for i, (doc, meta) in enumerate(zip(docs, metas), 1):
            source = meta.get("source", "未知") if meta else "未知"
            output_parts.append(f"[来源{i}] {source}\n{doc[:200]}")
        return "\n---\n".join(output_parts)
    except Exception as e:
        return f"知识库检索失败: {e}"


# ════════════════════════════════════════════════════════════
#  Agent 角色定义
# ════════════════════════════════════════════════════════════

# Agent 1: 选题策划师
planner_agent = Agent(
    role="选题策划师",
    goal="分析用户的需求，设计出温暖、安全的睡前故事主题、主角角色和故事场景",
    backstory="""你是一位经验丰富的儿童故事选题策划师，擅长从简单的用户需求中提炼出
    温暖的故事主题。你了解儿童心理，知道什么样的角色和场景能带来安全感和舒适感。
    你的设计总是以小动物或自然精灵为主角，情节温和。""",
    llm=deepseek_llm,
    verbose=True,
    allow_delegation=False,
)

# Agent 2: 资料搜集员
researcher_agent = Agent(
    role="资料搜集员",
    goal="利用知识库检索工具，为故事创作收集相关的参考素材和背景知识",
    backstory="""你是一位专业的资料搜集员，擅长使用检索工具从知识库中找到与故事主题
    相关的参考资料。你会分析选题策划师的方案，提取关键词进行检索，并将结果整理为
    创作素材清单。""",
    llm=deepseek_llm,
    verbose=True,
    allow_delegation=False,
    tools=[kb_search_tool],
)

# Agent 3: 故事创作师
writer_agent = Agent(
    role="故事创作师",
    goal="根据选题方案和参考资料，撰写符合创作铁律的睡前故事",
    backstory="""你是「月白」——一位温柔的睡前故事创作师。你的文字柔和有质感，
    能把读者送入安稳的睡眠。你严格遵守创作铁律：安全感第一、角色限定为小动物或自然精灵、
    只有「小小的愿望→温柔的旅程→安定的归来」的弧线、五感优先、节奏递减、句式交替。
    禁止使用「突然」「猛地」「哭」「怕」「黑」等字眼。以「晚安」或安定意象收尾。""",
    llm=deepseek_llm,
    verbose=True,
    allow_delegation=False,
)

# Agent 4: 质量审核员
reviewer_agent = Agent(
    role="质量审核员",
    goal="对照创作铁律逐条审核故事质量，发现问题并优化，输出最终定稿",
    backstory="""你是一位严格的睡前故事质量审核员，负责对照8条创作铁律逐一检查：
    R1.安全无恐怖元素  R2.角色为小动物/自然精灵  R3.情节弧线正确
    R4.五感优先+节奏递减  R5.无违禁字眼  R6.字数350-450字
    R7.无推理过程  R8.以晚安或安定意象收尾。
    你会给出评分、指出问题并直接修改输出优化后的定稿。""",
    llm=deepseek_llm,
    verbose=True,
    allow_delegation=False,
)


# ════════════════════════════════════════════════════════════
#  任务链定义（串行流水线）
# ════════════════════════════════════════════════════════════

def build_crew(user_prompt: str):
    """根据用户输入构建 Crew 任务链"""

    # Task 1: 选题策划
    plan_task = Task(
        description=f"""
用户需求：{user_prompt}

请分析用户需求，设计睡前故事的：
1. 故事主题（一句话概括）
2. 主角设定（名字、物种、性格特点）
3. 故事场景（时间、地点、氛围）
4. 核心情节线（愿望→旅程→归来）

输出格式：
【主题】...
【主角】...
【场景】...
【情节线】...
""",
        agent=planner_agent,
        expected_output="结构化的故事选题方案，包含主题、主角、场景、情节线",
    )

    # Task 2: 资料搜集
    research_task = Task(
        description="""
根据选题策划师的方案，使用"知识库检索工具"搜索与故事主题、主角、场景相关的参考资料。

检索策略：
- 用故事主题和主角特征作为检索关键词
- 整理检索到的有用素材
- 如果知识库中没有相关内容，说明并基于自身知识补充

输出格式：
【检索关键词】...
【参考素材】...
【创作建议】...
""",
        agent=researcher_agent,
        expected_output="检索到的参考素材清单和创作建议",
        context=[plan_task],
    )

    # Task 3: 故事创作
    write_task = Task(
        description="""
根据选题方案和参考资料，撰写一篇睡前故事。

严格遵守创作铁律：
R1. 安全感第一：不得出现恐怖、紧张、悲伤元素
R2. 角色限定：主角只能是小动物或自然精灵
R3. 情节纯度：只有「小小的愿望→温柔的旅程→安定的归来」
R4. 五感优先 + 节奏递减 + 句式交替
R5. 禁止用「突然」「猛地」「哭」「怕」「黑」等字眼
R6. 字数：350-450字
R7. 不要输出推理过程，只输出故事正文
R8. 以「晚安」或安定意象收尾

只输出故事正文，不要加标题或标注。
""",
        agent=writer_agent,
        expected_output="一篇350-450字的睡前故事正文",
        context=[plan_task, research_task],
    )

    # Task 4: 质量审核
    review_task = Task(
        description="""
审核故事创作师的输出，对照以下8条创作铁律逐一检查：

R1. 安全感第一：无恐怖、紧张、悲伤元素？
R2. 角色限定：主角是小动物或自然精灵？
R3. 情节弧线：愿望→旅程→归来？
R4. 五感优先 + 节奏递减 + 句式交替？
R5. 无违禁字眼（突然/猛地/哭/怕/黑）？
R6. 字数 350-450字？
R7. 无推理过程，纯故事正文？
R8. 以「晚安」或安定意象收尾？

审核流程：
1. 逐条给出 通过/不通过 判定
2. 计算总评分（满分8分）
3. 如有不通过项，直接修改并输出优化后的定稿
4. 如全部通过，原样输出

输出格式：
【审核结果】
R1: ✅/❌ ...
R2: ✅/❌ ...
...
总评分：x/8

【最终定稿】
（优化后的故事正文）
""",
        agent=reviewer_agent,
        expected_output="审核结果和最终定稿故事",
        context=[write_task],
    )

    crew = Crew(
        agents=[planner_agent, researcher_agent, writer_agent, reviewer_agent],
        tasks=[plan_task, research_task, write_task, review_task],
        process=Process.sequential,
        verbose=True,
    )

    return crew


# ════════════════════════════════════════════════════════════
#  单 Agent 基线（直接 LLM 调用，模拟 app.py 的方式）
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


def single_agent_story(user_prompt: str) -> str:
    """单 Agent 直接调用 LLM（模拟 app.py 的方式）"""
    from openai import OpenAI
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.80,
        max_tokens=1024,
    )
    return resp.choices[0].message.content.strip()


# ════════════════════════════════════════════════════════════
#  质量评估函数
# ════════════════════════════════════════════════════════════
def evaluate_story(story: str) -> dict:
    """自动评估故事质量，返回各项评分"""
    story_clean = story.strip()
    word_count = len(story_clean.replace("\n", "").replace(" ", ""))

    # 违禁词检查
    banned_words = ["突然", "猛地", "哭", "怕", "黑"]
    found_banned = [w for w in banned_words if w in story_clean]

    # 结尾检查
    good_endings = ["晚安", "睡", "梦", "安", "静", "月", "星", "光", "暖", "宁"]
    has_good_ending = any(story_clean.endswith(w) or w in story_clean[-20:] for w in good_endings)

    # 五感词汇检查
    sense_words = {
        "视觉": ["看", "光", "亮", "色", "闪烁", "映", "辉", "莹"],
        "听觉": ["听", "声", "响", "歌", "吟", "呢喃", "低语", "沙沙"],
        "触觉": ["触", "暖", "凉", "柔", "轻", "抚", "贴", "温"],
        "嗅觉": ["闻", "香", "芬芳", "清新", "气息"],
        "味觉": ["尝", "甜", "甘", "蜜"],
    }
    senses_found = {}
    for sense, words in sense_words.items():
        matched = [w for w in words if w in story_clean]
        if matched:
            senses_found[sense] = matched

    # 评分计算
    score = 0
    details = []

    # R1 安全性（无违禁恐怖词）
    r1_pass = len(found_banned) == 0
    if r1_pass:
        score += 1
    details.append(f"R1 安全性: {'✅ 通过' if r1_pass else '❌ 发现违禁词: ' + ', '.join(found_banned)}")

    # R5 违禁字眼
    r5_pass = len(found_banned) == 0
    if r5_pass:
        score += 1
    details.append(f"R5 无违禁字: {'✅ 通过' if r5_pass else '❌ 失败'}")

    # R6 字数
    r6_pass = 300 <= word_count <= 500
    if r6_pass:
        score += 1
    details.append(f"R6 字数({word_count}字): {'✅ 通过' if r6_pass else '❌ 超出范围'}")

    # R8 结尾意象
    r8_pass = has_good_ending
    if r8_pass:
        score += 1
    details.append(f"R8 安定结尾: {'✅ 通过' if r8_pass else '❌ 未检测到安定意象'}")

    # R4 五感丰富度
    sense_count = len(senses_found)
    r4_pass = sense_count >= 2
    if r4_pass:
        score += 1
    details.append(f"R4 五感({sense_count}种: {', '.join(senses_found.keys())}): {'✅ 通过' if r4_pass else '❌ 不足'}")

    # 结构完整性（粗略检查是否有起承转合）
    has_wish = any(w in story_clean for w in ["想", "希望", "愿望", "渴望", "梦"])
    has_journey = any(w in story_clean for w in ["走", "飞", "寻", "穿", "过", "沿"])
    has_return = any(w in story_clean for w in ["回", "归", "到家", "窝", "安", "睡"])
    r3_pass = has_wish and has_journey and has_return
    if r3_pass:
        score += 1
    details.append(f"R3 情节弧线(愿→旅→归): {'✅ 通过' if r3_pass else '❌ 不完整'}")

    return {
        "score": score,
        "total": 6,
        "word_count": word_count,
        "details": details,
        "senses": senses_found,
        "banned_words": found_banned,
    }


# ════════════════════════════════════════════════════════════
#  主函数
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    test_prompt = "讲一个关于小狐狸找星星的睡前故事"

    print("=" * 60)
    print("  CrewAI 多 Agent 任务链 vs 单 Agent 对比测试")
    print("=" * 60)
    print(f"\n  测试提示词: {test_prompt}\n")

    # ── 1. 单 Agent 基线 ──
    print("─" * 60)
    print("  [1/2] 单 Agent 模式（直接 LLM 调用）")
    print("─" * 60)
    single_result = single_agent_story(test_prompt)
    print(single_result)
    print()

    single_eval = evaluate_story(single_result)
    print(f"  质量评分: {single_eval['score']}/{single_eval['total']}")
    for d in single_eval["details"]:
        print(f"    {d}")
    print()

    # ── 2. CrewAI 多 Agent ──
    print("─" * 60)
    print("  [2/2] CrewAI 多 Agent 模式（4 Agent 任务链）")
    print("  Agent 1: 选题策划师 → Agent 2: 资料搜集员 → Agent 3: 故事创作师 → Agent 4: 质量审核员")
    print("─" * 60)

    crew = build_crew(test_prompt)
    crew_result = crew.kickoff()
    crew_output = str(crew_result)

    print()
    print("  CrewAI 最终输出:")
    print(crew_output)
    print()

    crew_eval = evaluate_story(crew_output)
    print(f"  质量评分: {crew_eval['score']}/{crew_eval['total']}")
    for d in crew_eval["details"]:
        print(f"    {d}")
    print()

    # ── 3. 对比总结 ──
    print("=" * 60)
    print("  对比总结")
    print("=" * 60)
    print(f"  {'指标':<16} {'单Agent':>10} {'CrewAI多Agent':>15}")
    print(f"  {'─' * 50}")
    print(f"  {'质量评分':<16} {single_eval['score']:>5}/{single_eval['total']:<5} {crew_eval['score']:>8}/{crew_eval['total']:<7}")
    print(f"  {'字数':<16} {single_eval['word_count']:>10} {crew_eval['word_count']:>15}")
    print(f"  {'违禁词':<16} {len(single_eval['banned_words']):>10} {len(crew_eval['banned_words']):>15}")
    print(f"  {'五感种类':<16} {len(single_eval['senses']):>10} {len(crew_eval['senses']):>15}")
    print()

    # 保存结果
    results = {
        "prompt": test_prompt,
        "single_agent": {
            "story": single_result,
            "eval": single_eval,
        },
        "crewai_multi_agent": {
            "story": crew_output,
            "eval": crew_eval,
        },
    }

    output_path = os.path.join(_PROJECT_DIR, "crewai_comparison_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  结果已保存: {output_path}")
