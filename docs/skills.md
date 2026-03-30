# Agent Skills System — Smart Health Assistant

[中文文档 ↓](#agent-技能系统——大健康智能助手)

---

## Overview

The Skills System gives each LangGraph agent a set of **modular, reusable capabilities** beyond simple tool calls. Each skill is a self-contained Python class with typed Pydantic I/O, stored in its own subdirectory alongside a `SKILL.md` metadata file that the registry reads at startup to auto-discover and wire up the skill as a LangChain `@tool`.

> **LangGraph compatibility note:** LangGraph has no native "skill" concept. This is a custom implementation that packages domain logic as standard LangChain tools — the pattern recommended by the LangChain team for modular agent capabilities. The `SKILL.md` format is inspired by the [LangChain Deep Agents skills spec](https://docs.langchain.com/oss/python/deepagents/skills).

---

## Architecture

```
User message
    │
    ▼
Agent Node (clinic / advisor / report / pharmacy)
    │
    ├─ get_agent_tools(tags=["clinic"])
    │       │
    │       └─ SkillRegistry scans backend/skills/*/SKILL.md
    │               └─ Returns matching skills wrapped as @tool
    │
    ├─ create_react_agent(llm, tools=[load_skill, *skill_tools, ...])
    │
    └─ ReAct loop — LLM decides when to call which skill
            └─ skill.run(**kwargs) → SkillOutput (structured Pydantic)
```

### Key files

```
backend/skills/
├── __init__.py              # Registry + get_agent_tools() + load_skill tool
├── base.py                  # BaseSkill abstract class, SkillOutput Pydantic base
├── emergency_triage/
│   ├── SKILL.md             # Metadata: name, description, tags, version
│   ├── __init__.py
│   └── skill.py             # EmergencyTriageSkill implementation
├── symptom_scorer/
│   ├── SKILL.md
│   └── skill.py
├── health_calculator/
│   ├── SKILL.md
│   └── skill.py
├── lab_interpreter/
│   ├── SKILL.md
│   └── skill.py
├── risk_assessor/
│   ├── SKILL.md
│   └── skill.py
└── medication_calculator/
    ├── SKILL.md
    └── skill.py
```

---

## Installed Skills

| Skill | Tags | Purpose |
|---|---|---|
| `emergency_triage` | clinic | Rule-based red-flag safety gate — called first on any symptom; returns RED / YELLOW / GREEN |
| `symptom_scorer` | clinic | Severity score 0–100 with triage colour and recommended wait time |
| `health_calculator` | advisor, clinic | BMI, ideal weight (Devine formula), TDEE (Mifflin-St Jeor), waist-height ratio |
| `lab_interpreter` | report, clinic | Compares lab values against reference ranges; flags HIGH / LOW / NORMAL with clinical notes |
| `risk_assessor` | advisor, clinic | 10-year CVD risk (Framingham) + type-2 diabetes risk (FINDRISC 8-item scale) |
| `medication_calculator` | pharmacy, clinic | Weight/age-based dose calculation for common drug classes with safety warnings |

### Tag → agent mapping

| Tag | Agent that auto-loads it |
|---|---|
| `clinic` | clinic_node |
| `advisor` | advisor_node |
| `report` | report_node |
| `pharmacy` | pharmacy_node |

A skill with multiple tags is loaded by all matching agents.

---

## The `load_skill` Universal Tool

Every agent also receives `load_skill` — a runtime dispatcher that lets the LLM call **any** registered skill by name, even if it wasn't pre-loaded for that agent:

```python
# The LLM invokes it like this during a ReAct step:
load_skill(
    skill_name="health_calculator",
    params_json='{"height_cm": 170, "weight_kg": 70, "age": 35, "gender": "male"}'
)
```

This avoids having to enumerate every skill in every agent's tool list while still keeping them all accessible.

---

## SkillOutput Contract

Every skill returns a Pydantic model inheriting from `SkillOutput`. The following fields are **mandatory**:

| Field | Type | Notes |
|---|---|---|
| `skill_name` | `str` | Echo of `BaseSkill.name` |
| `success` | `bool` | Whether the skill ran without errors |
| `confidence` | `float` | 0.0–1.0 estimate of result reliability |
| `disclaimer` | `str` | Agent **must** display this to the user |

---

## Adding a New Skill

### 1. Create the directory

```bash
mkdir backend/skills/my_skill
touch backend/skills/my_skill/__init__.py
```

### 2. Write `SKILL.md`

The registry reads the YAML frontmatter. The `description` field is passed directly to the LLM as the tool's description — make it specific about when to call the skill.

```markdown
---
name: my_skill
description: |
  Describe when the agent should call this skill, with concrete trigger phrases.
  Which agents use it. What it returns.
tags: [advisor, clinic]   # any of: advisor, clinic, report, pharmacy
version: "1.0"
---

# My Skill

Detailed documentation: inputs, outputs, agent instructions, edge cases.
```

### 3. Implement `skill.py`

```python
from pydantic import BaseModel, Field
from skills.base import BaseSkill, SkillOutput

class MySkillInput(BaseModel):
    param: str = Field(description="Parameter description in Chinese")

class MySkillOutput(SkillOutput):
    result: str

class MySkill(BaseSkill):
    name = "my_skill"       # must match SKILL.md frontmatter name
    description = "..."
    tags = ["advisor"]      # must match SKILL.md frontmatter tags

    def run(self, **kwargs) -> MySkillOutput:
        data = MySkillInput(**kwargs)
        # ... compute result ...
        return MySkillOutput(
            skill_name=self.name,
            success=True,
            confidence=0.9,
            disclaimer="本结果仅供参考，不替代专业医学意见。",
            result="...",
        )
```

**That's all.** The registry auto-discovers the skill on next startup — no manual registration step needed.

### 4. Verify

```python
from skills import get_registry
registry = get_registry()
print(registry.list_skills())                    # all skills
print(registry.list_skills(tags=["advisor"]))    # advisor-tagged only
```

### 5. Update agent system prompt (optional)

Tell the agent when to call your new skill by adding a line to the system prompt in the relevant agent file:

```python
# In backend/agents/advisor.py → _build_system_prompt()
"- my_skill：当用户询问XYZ时调用"
```

---

## SKILL.md Format Reference

```yaml
---
name: skill_name          # required — snake_case, unique
description: |            # required — shown to LLM as tool description
  When to trigger.
  What it returns.
tags: [advisor, clinic]   # required — controls which agents auto-load it
version: "1.0"            # optional but recommended
---
```

The Markdown body below the frontmatter is human documentation — it is not parsed by the registry but is used in `SKILL.md` by each skill as agent instructions (shown in the skill's tool description context).

---

# Agent 技能系统——大健康智能助手

[English Documentation ↑](#agent-skills-system--smart-health-assistant)

---

## 概述

技能系统为每个 LangGraph 智能体提供一套**模块化、可复用的专业能力**，超越了普通工具调用的范畴。每个技能是一个独立的 Python 类，具有类型化的 Pydantic 输入/输出，存储在各自的子目录中，并附带一个 `SKILL.md` 元数据文件。注册表在启动时读取该文件，自动发现并将技能封装为 LangChain `@tool`。

> **与 LangGraph 的兼容性说明：** LangGraph 本身没有原生的"技能"概念。本实现将领域逻辑封装为标准 LangChain 工具——这是 LangChain 团队推荐的模块化智能体能力扩展方式。`SKILL.md` 格式参考了 [LangChain Deep Agents 技能规范](https://docs.langchain.com/oss/python/deepagents/skills)。

---

## 系统架构

```
用户输入
    │
    ▼
智能体节点（clinic / advisor / report / pharmacy）
    │
    ├─ get_agent_tools(tags=["clinic"])
    │       │
    │       └─ SkillRegistry 扫描 backend/skills/*/SKILL.md
    │               └─ 返回匹配的技能（封装为 @tool）
    │
    ├─ create_react_agent(llm, tools=[load_skill, *skill_tools, ...])
    │
    └─ ReAct 循环——LLM 自主决定何时调用哪个技能
            └─ skill.run(**kwargs) → SkillOutput（结构化 Pydantic 对象）
```

### 核心文件

```
backend/skills/
├── __init__.py              # 注册表 + get_agent_tools() + load_skill 工具
├── base.py                  # BaseSkill 抽象类、SkillOutput Pydantic 基类
├── emergency_triage/
│   ├── SKILL.md             # 元数据：name、description、tags、version
│   ├── __init__.py
│   └── skill.py             # EmergencyTriageSkill 实现
├── symptom_scorer/
│   ├── SKILL.md
│   └── skill.py
├── health_calculator/
│   ├── SKILL.md
│   └── skill.py
├── lab_interpreter/
│   ├── SKILL.md
│   └── skill.py
├── risk_assessor/
│   ├── SKILL.md
│   └── skill.py
└── medication_calculator/
    ├── SKILL.md
    └── skill.py
```

---

## 已安装技能

| 技能 | 标签 | 功能 |
|---|---|---|
| `emergency_triage` | clinic | 基于规则的红色预警安全门——症状描述后优先调用，返回 RED / YELLOW / GREEN |
| `symptom_scorer` | clinic | 症状严重程度评分（0-100）含分诊颜色和建议就诊等待时间 |
| `health_calculator` | advisor, clinic | BMI、理想体重（Devine 公式）、每日热量需求（Mifflin-St Jeor）、腰围身高比 |
| `lab_interpreter` | report, clinic | 对比参考范围标注 HIGH / LOW / NORMAL，附临床意义说明 |
| `risk_assessor` | advisor, clinic | 10 年心血管风险（Framingham）+ 2 型糖尿病风险（FINDRISC 8 项量表） |
| `medication_calculator` | pharmacy, clinic | 常见药物按体重/年龄计算推荐剂量，含安全警示 |

### 标签与智能体对应关系

| 标签 | 自动加载该技能的智能体 |
|---|---|
| `clinic` | clinic_node（预问诊） |
| `advisor` | advisor_node（健康顾问） |
| `report` | report_node（报告解读） |
| `pharmacy` | pharmacy_node（药管家） |

拥有多个标签的技能将被所有匹配的智能体加载。

---

## `load_skill` 通用工具

每个智能体还会收到 `load_skill`——一个运行时调度器，允许 LLM 按名称调用**任意**已注册技能，即使该技能未预先加载给该智能体：

```python
# LLM 在 ReAct 步骤中这样调用：
load_skill(
    skill_name="health_calculator",
    params_json='{"height_cm": 170, "weight_kg": 70, "age": 35, "gender": "male"}'
)
```

这样无需在每个智能体的工具列表中枚举所有技能，同时保持所有技能均可访问。

---

## SkillOutput 输出约定

每个技能返回一个继承自 `SkillOutput` 的 Pydantic 模型。以下字段**必须**提供：

| 字段 | 类型 | 说明 |
|---|---|---|
| `skill_name` | `str` | 回显 `BaseSkill.name` 的值 |
| `success` | `bool` | 技能是否成功运行 |
| `confidence` | `float` | 0.0–1.0，结果可信度估计 |
| `disclaimer` | `str` | 智能体**必须**向用户展示此免责声明 |

---

## 添加新技能

### 第一步：创建目录

```bash
mkdir backend/skills/my_skill
touch backend/skills/my_skill/__init__.py
```

### 第二步：编写 `SKILL.md`

注册表读取 YAML frontmatter。`description` 字段直接传递给 LLM 作为工具描述——请具体说明何时调用。

```markdown
---
name: my_skill
description: |
  描述智能体何时应调用此技能，包括具体的触发场景和用户用语。
  标注适用的智能体。说明返回内容。
tags: [advisor, clinic]   # 可选值：advisor、clinic、report、pharmacy
version: "1.0"
---

# 技能名称

详细文档：输入、输出、智能体使用说明、边界情况处理。
```

### 第三步：实现 `skill.py`

```python
from pydantic import BaseModel, Field
from skills.base import BaseSkill, SkillOutput

class MySkillInput(BaseModel):
    param: str = Field(description="参数说明（中文）")

class MySkillOutput(SkillOutput):
    result: str

class MySkill(BaseSkill):
    name = "my_skill"       # 必须与 SKILL.md 中的 name 一致
    description = "..."
    tags = ["advisor"]      # 必须与 SKILL.md 中的 tags 一致

    def run(self, **kwargs) -> MySkillOutput:
        data = MySkillInput(**kwargs)
        # ... 计算结果 ...
        return MySkillOutput(
            skill_name=self.name,
            success=True,
            confidence=0.9,
            disclaimer="本结果仅供参考，不替代专业医学意见。",
            result="...",
        )
```

**完成。** 注册表将在下次启动时自动发现该技能——无需手动注册。

### 第四步：验证

```python
from skills import get_registry
registry = get_registry()
print(registry.list_skills())                    # 所有已注册技能
print(registry.list_skills(tags=["advisor"]))    # 仅 advisor 标签技能
```

### 第五步：更新智能体系统提示（可选）

在对应智能体文件的系统提示中添加一行，告知智能体何时调用新技能：

```python
# 例如在 backend/agents/advisor.py 的 _build_system_prompt() 中：
"- my_skill：当用户询问XYZ时调用"
```

---

## SKILL.md 格式参考

```yaml
---
name: skill_name          # 必填——snake_case，全局唯一
description: |            # 必填——直接作为 LLM 的工具描述使用
  何时触发。
  返回什么。
tags: [advisor, clinic]   # 必填——控制哪些智能体自动加载
version: "1.0"            # 可选，建议填写
---
```

frontmatter 下方的 Markdown 正文是面向人类的文档说明，注册表不解析它，但它作为每个技能的智能体使用说明在 `SKILL.md` 中发挥文档作用。
