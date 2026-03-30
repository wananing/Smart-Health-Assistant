"""
Pharmacy Agent Node.

Applies best practices from:
  - LangChain Architecture: Pydantic tool input schemas, StructuredTool
  - Prompt Engineering: Structured output with Pydantic, Chain-of-Thought
  - RAG Implementation: Metadata-filtered retrieval for drug knowledge

Tools:
  1. search_drug_info        - 查询药品信息（说明书、适应症、用法用量）
  2. check_drug_interaction  - 检查药物间相互作用
  3. find_nearby_pharmacy    - 查找附近药店
  4. get_otc_recommendation  - 根据症状推荐OTC药品
"""
import json
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent
from agents.state import MainAgentState
from agents.llm import get_chat_llm
from rag.knowledge_base import get_knowledge_base
from skills import get_agent_tools, load_skill


# ─── MOCK DATA ────────────────────────────────────────────────────────────────

_DRUG_DATABASE = {
    "布洛芬": {
        "generic_name": "布洛芬",
        "brand_names": ["芬必得", "美林"],
        "category": "非甾体抗炎药（OTC）",
        "indications": ["发热", "头痛", "牙痛", "肌肉酸痛", "关节疼痛", "痛经"],
        "dosage": "成人：每次200-400mg，每4-6小时一次，每日不超过1200mg",
        "contraindications": ["消化性溃疡活动期", "严重肝肾功能不全", "对阿司匹林过敏者"],
        "warnings": ["饭后服用可减少胃肠道刺激", "孕晚期禁用", "老年人慎用"],
        "price_range": "10-30元/盒",
        "otc": True,
    },
    "对乙酰氨基酚": {
        "generic_name": "对乙酰氨基酚",
        "brand_names": ["泰诺", "必理通", "百服宁"],
        "category": "解热镇痛药（OTC）",
        "indications": ["发热", "头痛", "关节痛", "肌肉痛", "牙痛"],
        "dosage": "成人：每次325-650mg，每4-6小时一次，每日不超过4000mg",
        "contraindications": ["严重肝功能不全", "对本品过敏者"],
        "warnings": ["禁止与其他含对乙酰氨基酚产品同时服用", "避免饮酒", "肝功能异常者慎用"],
        "price_range": "8-25元/盒",
        "otc": True,
    },
    "氨氯地平": {
        "generic_name": "苯磺酸氨氯地平",
        "brand_names": ["络活喜", "施慧达"],
        "category": "钙通道阻滞剂（处方药）",
        "indications": ["高血压", "稳定型心绞痛"],
        "dosage": "成人：初始5mg，每日一次；可增至10mg，每日一次",
        "contraindications": ["对本品过敏", "严重低血压", "心源性休克"],
        "warnings": ["需要处方才能购买", "不要突然停药", "可能引起踝部水肿"],
        "price_range": "30-80元/盒",
        "otc": False,
    },
    "二甲双胍": {
        "generic_name": "盐酸二甲双胍",
        "brand_names": ["格华止", "美迪康"],
        "category": "双胍类降糖药（处方药）",
        "indications": ["2型糖尿病"],
        "dosage": "成人：初始500mg，每日2次，随餐服用；最大剂量2550mg/日",
        "contraindications": ["肾功能不全（eGFR<30）", "肝功能不全", "糖尿病酮症酸中毒"],
        "warnings": ["需要处方才能购买", "需监测肾功能", "造影检查前后需暂停"],
        "price_range": "10-50元/盒",
        "otc": False,
    },
}

_INTERACTION_DATABASE = {
    ("布洛芬", "阿司匹林"): {
        "severity": "中等",
        "description": "两种NSAIDs药物合用会增加胃肠道出血和溃疡的风险，同时可能降低阿司匹林的心脏保护作用。",
        "recommendation": "通常不建议同时使用，如需同时使用应咨询医生。",
    },
    ("布洛芬", "华法林"): {
        "severity": "严重",
        "description": "布洛芬可增强华法林的抗凝效果，显著升高出血风险。",
        "recommendation": "禁止同时使用，如必须使用应在医生监督下密切监测INR。",
    },
    ("对乙酰氨基酚", "酒精"): {
        "severity": "严重",
        "description": "酒精会加重对乙酰氨基酚的肝毒性，可导致严重肝损伤。",
        "recommendation": "服药期间严禁饮酒。",
    },
}

_NEARBY_PHARMACIES = [
    {"name": "国大药房（中关村店）", "distance": "0.3公里", "hours": "08:00-22:00",
     "phone": "010-12345678", "type": "连锁药店", "supports_insurance": True},
    {"name": "北京医保全新大药房", "distance": "0.5公里", "hours": "07:00-23:00",
     "phone": "010-87654321", "type": "连锁药店", "supports_insurance": True},
    {"name": "同仁堂社区药店", "distance": "0.8公里", "hours": "09:00-21:00",
     "phone": "010-11223344", "type": "中西药店", "supports_insurance": False},
    {"name": "美团买药（30分钟送达）", "distance": "线上", "hours": "24小时",
     "phone": "线上订购", "type": "网上药店", "supports_insurance": False},
]


# ─── PYDANTIC TOOL SCHEMAS (Best Practice: LangChain Architecture) ────────────

class DrugSearchInput(BaseModel):
    """Input schema for drug information lookup."""
    drug_name: str = Field(description="药品的通用名或商品名，如：布洛芬、泰诺、络活喜")


class DrugInteractionInput(BaseModel):
    """Input schema for drug interaction check."""
    drug1: str = Field(description="第一种药品名称")
    drug2: str = Field(description="第二种药品名称")


class OTCRecommendInput(BaseModel):
    """Input schema for OTC drug recommendation."""
    symptoms: str = Field(description="用户描述的症状，如：发烧头痛、咳嗽、胃痛等")


# ─── TOOLS ────────────────────────────────────────────────────────────────────

@tool(args_schema=DrugSearchInput)
async def search_drug_info(drug_name: str) -> str:
    """查询药品的详细信息，包括适应症、用法用量、禁忌证、价格区间等。
    同时从知识库检索相关医学信息以补充说明。"""
    result = {"tool": "drug_info", "query": drug_name}

    # Exact match first, then partial match
    matched = _DRUG_DATABASE.get(drug_name)
    if not matched:
        for key, val in _DRUG_DATABASE.items():
            brands = val.get("brand_names", [])
            if drug_name in brands or drug_name in key:
                matched = val
                break

    if matched:
        result["found"] = True
        result["drug"] = matched
    else:
        # Fall back to RAG search for drugs not in mock DB
        kb = get_knowledge_base()
        docs = await kb.aretrieve(f"{drug_name} 药品 用法 适应症", k=3)
        rag_info = kb.format_context(docs)
        result["found"] = False
        result["rag_info"] = rag_info or f"未找到{drug_name}的详细信息，建议前往正规医院或药店咨询药师。"

    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=DrugInteractionInput)
def check_drug_interaction(drug1: str, drug2: str) -> str:
    """检查两种药物之间是否存在相互作用，给出相互作用的严重程度和处理建议。"""
    result = {"tool": "drug_interaction", "drug1": drug1, "drug2": drug2}

    interaction = (
        _INTERACTION_DATABASE.get((drug1, drug2))
        or _INTERACTION_DATABASE.get((drug2, drug1))
    )

    if interaction:
        result["has_interaction"] = True
        result["interaction"] = interaction
    else:
        result["has_interaction"] = False
        result["message"] = f"未在数据库中发现{drug1}和{drug2}之间的已知重要相互作用，但请注意这不代表完全安全，如有疑虑请咨询药师或医生。"

    return json.dumps(result, ensure_ascii=False)


@tool
def find_nearby_pharmacy(location: str = "") -> str:
    """查找用户附近的实体药店和网上药店，包括营业时间、距离、是否支持医保刷卡。"""
    result = {
        "tool": "nearby_pharmacy",
        "location": location or "当前位置",
        "pharmacies": _NEARBY_PHARMACIES,
        "tip": "支持医保刷卡的药店可直接使用医保个人账户余额购药。",
    }
    return json.dumps(result, ensure_ascii=False)


@tool(args_schema=OTCRecommendInput)
async def get_otc_recommendation(symptoms: str) -> str:
    """根据用户描述的轻微症状，从知识库中检索并推荐合适的非处方药（OTC）建议。
    适用于普通感冒、轻微发烧、头痛、胃肠不适等常见症状。"""
    kb = get_knowledge_base()
    # Multi-query retrieval (Best Practice: RAG Implementation)
    queries = [
        f"{symptoms} 非处方药 OTC 用药建议",
        f"{symptoms} 治疗方法",
    ]
    all_docs = []
    for q in queries:
        docs = await kb.aretrieve(q, k=2)
        all_docs.extend(docs)

    # Deduplicate by page_content
    seen = set()
    unique_docs = []
    for d in all_docs:
        if d.page_content not in seen:
            seen.add(d.page_content)
            unique_docs.append(d)

    rag_context = kb.format_context(unique_docs[:4])
    result = {
        "tool": "otc_recommendation",
        "symptoms": symptoms,
        "knowledge": rag_context or "请根据症状咨询药师以获取个性化建议。",
        "disclaimer": "以下建议仅供参考，如症状持续超过3天或加重，请及时就医。",
    }
    return json.dumps(result, ensure_ascii=False)


# ─── AGENT ────────────────────────────────────────────────────────────────────

# Best Practice (Prompt Engineering): Role-based system prompt with clear
# constraints, structured output guidance, and safety guidelines
PHARMACY_SYSTEM_PROMPT = """你是大健康App中的"AI药师助手"，拥有丰富的药学知识，态度专业、亲切。

【职责范围】
- 查询药品信息（适应症、用法用量、注意事项）
- 检查药物相互作用，提示用药安全
- 推荐常见轻症的OTC（非处方）药品
- 帮助用户查找附近药店

【工具使用规则】
- 用户询问某药品信息、说明书、用法时 → 调用 search_drug_info
- 用户询问两种药能不能一起吃、药物冲突时 → 调用 check_drug_interaction
- 用户询问附近哪里能买到药时 → 调用 find_nearby_pharmacy
- 用户描述轻微症状（如感冒、头痛、胃痛）并想用药时 → 调用 get_otc_recommendation
- 用户询问"按体重/年龄应该吃多少剂量"时 → 调用技能 medication_calculator（通过 load_skill）

【安全原则】（Chain-of-Thought: 先判断安全性再给建议）
1. **处方药**：明确告知用户该药为处方药，必须凭处方购买，不得自行用药。
2. **急症识别**：发现危重症状（剧烈胸痛、呼吸困难、大出血等）立即建议拨打120。
3. **用药限制**：儿童、孕妇、哺乳期妇女、老年人的用药建议要格外谨慎，并建议咨询医生。
4. **免责声明**：所有建议仅供参考，不能替代执业药师或医生的专业意见。

【输出格式】
- 简洁明了，适合移动端阅读
- 重要警告信息置于回答开头
- 使用列表格式展示药品信息"""

_PHARMACY_TOOLS = [
    search_drug_info,
    check_drug_interaction,
    find_nearby_pharmacy,
    get_otc_recommendation,
]

# Tool names that trigger frontend card rendering
PHARMACY_CARD_TOOLS = {t.name for t in _PHARMACY_TOOLS}

# Tool names → card payload types for frontend rendering
PHARMACY_TOOL_TO_CARD_TYPE = {
    "search_drug_info": "medication_task",
    "find_nearby_pharmacy": "hospital_list",
}


async def pharmacy_node(state: MainAgentState) -> dict:
    """
    Pharmacy agent: ReAct sub-agent with Pydantic-validated tool schemas.
    Handles drug info, interactions, OTC recommendations, and pharmacy lookup.
    """
    llm = get_chat_llm("balanced")
    user_info = state.get("user_info", {})

    extra_context = ""
    age = user_info.get("age")
    elder_mode = user_info.get("elder_mode", False)
    history = user_info.get("medical_history", "")

    if age:
        extra_context += f"\n\n用户年龄：{age}岁。"
        if age >= 65:
            extra_context += "老年患者，用药建议需特别谨慎，注意肝肾功能影响。"
    if history:
        extra_context += f"\n用户既往病史：{history}，给出建议时需综合考虑。"
    if elder_mode:
        extra_context += "\n请使用通俗易懂的语言，避免专业术语。"

    system_prompt = PHARMACY_SYSTEM_PROMPT + extra_context

    # Load pharmacy-tagged skills (medication_calculator) alongside core tools
    skill_tools = get_agent_tools(tags=["pharmacy"])

    agent = create_react_agent(
        llm,
        tools=[*_PHARMACY_TOOLS, load_skill, *skill_tools],
        prompt=SystemMessage(content=system_prompt),
    )

    sub_result = await agent.ainvoke({"messages": state["messages"]})
    original_count = len(state["messages"])
    new_messages = sub_result["messages"][original_count:]
    return {"messages": new_messages}
