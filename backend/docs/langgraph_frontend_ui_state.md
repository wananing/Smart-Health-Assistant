# LangGraph 状态流式透传与前端 UI 渲染设计文档

在构建基于 Agent 的应用（如医保智能体、报告解读智能体）时，用户往往需要等待较长的时间（期间 Agent 可能会经历：分析意图 -> 检索知识库 -> 调用工具查询 API -> 综合生成等多个步骤）。
如果只在最后返回一段文本，用户体验会非常差（表现为长时间“卡顿”）。因此，我们需要将 LangGraph 内部的中间状态（如 Tool Call、Thinking 过程）以前端友好的形式流式透传（Streaming）出去，渲染成高级的交互式 UI。

## 1. 核心思路

1. **后端 (Backend)**: 利用 LangGraph/LangChain 原生的 `astream_events(version="v2")` 接口，拦截内部发生的各类生命周期事件（包括模型推理、工具开始、工具结束）。将其包装成统一格式的 Server-Sent Events (SSE) JSON 抛给前端。
2. **前端数据结构 (Frontend State)**: 消息列表中的一个“消息 (Message)”不再只是一个单一的字符串，而是一个复合结构，包含“状态流 (Steps/Tools)”和“正文 (Content)”。
3. **前端渲染 (Frontend UI)**: 提供类似 ChatGPT/Claude 的“折叠面板 (Accordion)”，展示大模型的思考或动作过程（如 `[✓] 正在查询医保消费记录...`），正文部分则实时打字机输出。

## 2. 后端服务端流设计 (Backend Event Streaming)

在 FastAPI 的路由接口中，我们需要解析 LangGraph 的原始事件池。

### 2.1 定义统一的 SSE 传输协议 (JSON Payload)

为了让前端轻松解析，我们规定后端每个 SSE Chunk 的 `data:` 必须是一段 JSON，包含 `type` 和 `content` 或更多元数据。

```json
// 场景一：模型正在打字输出正文
{"type": "text", "content": "您好，"}

// 场景二：智能体准备调用工具（如：查医保）
{"type": "tool_start", "tool_name": "get_insurance_balance", "content": "正在查询医保余额..."}

// 场景三：智能体工具调用完成
{"type": "tool_end", "tool_name": "get_insurance_balance", "content": "查询成功"}

// 场景四：节点流转开始 (可选)
{"type": "node_start", "node_name": "retriever", "content": "正在检索医保政策..."}
```

### 2.2 FastAPI SSE 发生器实现 (Generator Implementation)

在 `main.py` 中：

```python
import json
from fastapi.responses import StreamingResponse
from langgraph_types import MainAgentState
from models.langgraph_router import master_app

async def chat_event_generator(initial_state: MainAgentState):
    """
    侦听 LangGraph 的 astream_events，将其转化为前端协议标准 JSON
    """
    async for event in master_app.astream_events(initial_state, version="v2"):
        kind = event["event"]
        
        # 1. 大模型生成的实时聊天文本 (Token by Token)
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"].content
            if chunk:
                payload = json.dumps({"type": "text", "content": chunk}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                
        # 2. 工具调用开始 (例如大模型决定使用某个 Tool)
        elif kind == "on_tool_start":
            tool_name = event["name"] # e.g., get_insurance_balance
            # 根据 tool_name 映射一个友好的中文名给前端
            friendly_msg = map_tool_to_friendly_name(tool_name)
            payload = json.dumps({
                "type": "tool_start", 
                "tool_name": tool_name,
                "content": friendly_msg
            }, ensure_ascii=False)
            yield f"data: {payload}\n\n"
            
        # 3. 工具调用结束
        elif kind == "on_tool_end":
            tool_name = event["name"]
            payload = json.dumps({
                "type": "tool_end",
                "tool_name": tool_name,
                "content": "已完成"
            }, ensure_ascii=False)
            yield f"data: {payload}\n\n"

        # 4. 图节点进入 (反映大阶段切换：如意图分类 -> 知识检索)
        elif kind == "on_chain_start":
            # 过滤掉内部的基础 LCEL chain，只保留 graph node级别的名字 (如 retriever, generator)
            node_name = event["name"]
            if node_name in ["router", "clinic_node", "report_node", "retriever", "tool_executor"]:
                payload = json.dumps({
                    "type": "node_start",
                    "node_name": node_name,
                    "content": f"进入处理节点：{node_name}"
                }, ensure_ascii=False)
                yield f"data: {payload}\n\n"

    # 结束标志
    yield 'data: {"type": "finish"}\n\n'
```

## 3. 前端解析与状态维护 (Frontend Parsing)

前端 `chatService.ts` 需要进行改造以解析多类型的流。

### 3.1 定义聚合状态 (TypeScript Interfaces)

我们在前端维护的一个“AI 消息体”应该如下所示：

```typescript
export interface ToolCallStatus {
  id: string; // 唯一ID标识这次工具调用
  toolName: string;
  statusText: string;
  isFinished: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  
  // 最终给用户看的大段 markdown 回复
  content: string; 
  
  // 运行过程中的中间状态记录（给用户看的“思考过程”）
  steps: ToolCallStatus[];
  
  // 消息生成状态
  isGenerating?: boolean; 
}
```

### 3.2 解析流数据 (Stream Processing)

```typescript
// 伪代码示例：前端 fetch response body 逐行解析
const processStream = async (reader: ReadableStreamDefaultReader, messageObj: ChatMessage) => {
  // ... decoder logic ...
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const jsonStr = line.slice(6);
      const data = JSON.parse(jsonStr);
      
      if (data.type === 'text') {
        // 增量拼接正文
        messageObj.content += data.content;
      } 
      else if (data.type === 'tool_start' || data.type === 'node_start') {
        // 在步骤数组里新增一项
        messageObj.steps.push({
          id: generateUniqueId(),
          toolName: data.tool_name || data.node_name,
          statusText: data.content,
          isFinished: false
        });
      } 
      else if (data.type === 'tool_end') {
        // 找到最后一项同名工具并标记完成
        const step = messageObj.steps.find(s => s.toolName === data.tool_name && !s.isFinished);
        if (step) {
          step.isFinished = true;
          step.statusText = `${step.statusText} (已完成)`;
        }
      }
      
      // 触发 UI 重新渲染 (如果是 React/Vue，通过 setter / Proxy 自动映射)
      triggerUpdate(messageObj);
    }
  }
}
```

## 4. UI 交互展示 (UI Rendering Example)

在界面组件上（例如 React 的 `<MessageBubble />`）：

```tsx
const MessageBubble = ({ message }: { message: ChatMessage }) => {
  return (
    <div className="message assistant">
      {/* 1. 如果有步骤信息，渲染“思考/操作过程”面板 */}
      {message.steps && message.steps.length > 0 && (
        <div className="thought-process-accordion">
          <details>
            <summary>
               {/* 折叠面板标题：可能显示最后一个操作中的状态 */}
               {message.steps.every(s => s.isFinished) ? '操作已完成' : 'AI 正在执行操作...'}
            </summary>
            <ul>
              {message.steps.map(step => (
                <li key={step.id}>
                  {step.isFinished ? '✅' : '⏳'} {step.statusText}
                </li>
              ))}
            </ul>
          </details>
        </div>
      )}

      {/* 2. 渲染正在打印或者已完成的正文 Markdown */}
      <div className="message-content markdown-body">
        {message.content && <MarkdownRenderer content={message.content} />}
      </div>
      
      {/* 3. 如果正在生成且没有正文，给一个光标游标 */}
      {message.isGenerating && !message.content && <span className="cursor-blink"></span>}
    </div>
  )
}
```

### 视觉效果预期：
- **一开始**：界面出现气泡，内部显示一个加载中的折叠栏：“`⏳ 正在检索医保政策...`”。正文为空。
- **几秒后**：折叠栏文字变成：“`✅ 正在检索医保政策... (已完成)`”，并在下方新增一行：“`⏳ 正在查询医保余额...`”。
- **几秒后**：工具全部分析完毕。下方空白处开始一行行打字机跳出：“根据您的医保账户记录，您近期消费了...”。
- 整个过程对用户极大缓解了焦虑，同时彰显了“Agentic 的智能感”。
