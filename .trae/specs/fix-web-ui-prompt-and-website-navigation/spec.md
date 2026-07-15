# Web UI 实时对话与官网导航增强 Spec

## Why
用户实际使用 Agent 投递小鹏汽车校招时发现两个问题：(1) Agent 遇到问题终止或运行中卡住时，用户只能在命令行给它新 prompt，Web UI 无法实时干预；(2) 小鹏汽车校招官网登录后初始页面没有职位列表，需要点击"即刻投递"等入口按钮才能看到岗位，Agent 不会自动识别并点击这些按钮，需要用户手动指导。

## What Changes
- **Web UI 实时对话功能**：用户可在 Agent 运行的任何阶段（运行中/已完成/出错）通过 Web UI 发送文本 prompt 干预 Agent 行为
  - Agent 运行中发送的消息会排队，当前 ainvoke 完成后自动以"历史 + 新消息"重新调用 Agent 继续
  - 新增"中断"按钮：取消当前 Agent 任务，然后以用户消息重新启动
  - 后端存储完整对话历史，支持多轮续接
- **官网入口按钮自动点击**：让 Agent 自主分析页面内容并决定点击哪个按钮
  - 新增 `click_element_by_text` 通用工具：Agent 提供按钮文本即可点击页面任意可见元素
  - 新增 `get_visible_buttons` 工具：返回当前页面所有可点击元素（按钮/链接）的文本列表，供 Agent 分析
  - 增强 `navigate_and_find_positions`：导航后先尝试自动点击常见入口按钮，失败则在返回信息中列出所有可见按钮供 Agent 决策
  - 系统提示中明确指导：页面无职位信息时，先调用 `get_visible_buttons` 查看可点击元素，再调用 `click_element_by_text` 点击合适的入口

## Impact
- Affected code:
  - `src/job_application_agent_langchain/web/session_manager.py` — 存储对话历史，支持续接与中断
  - `src/job_application_agent_langchain/web/routes.py` — 新增消息发送与中断端点
  - `src/job_application_agent_langchain/web/app.py` — WebSocket 处理 user_message
  - `src/job_application_agent_langchain/web/static/js/app.js` — 前端对话 UI 与中断按钮
  - `src/job_application_agent_langchain/web/static/index.html` — 对话区域 HTML
  - `src/job_application_agent_langchain/web/static/css/style.css` — 对话区域样式
  - `src/job_application_agent_langchain/agents/company_agent.py` — 传递历史消息、更新系统提示
  - `src/job_application_agent_langchain/agents/search.py` — 增强导航、新增工具
  - `src/job_application_agent_langchain/browser/automation.py` — 新增按文本点击与获取可见按钮方法

## ADDED Requirements

### Requirement: Web UI 实时对话
系统 SHALL 允许用户在 Agent 运行的任何阶段（运行中/已完成/出错）通过 Web UI 发送文本 prompt 干预 Agent。

#### Scenario: Agent 运行中用户发送指导
- **WHEN** Agent 正在运行
- **AND** 用户在 Web UI 对话框输入"这个页面需要先点击即刻投递按钮"
- **THEN** 消息排队等待当前 Agent 步骤完成
- **AND** 当前 ainvoke 返回后，系统自动以"完整历史 + 新消息"重新调用 Agent

#### Scenario: Agent 出错后用户给新指令
- **WHEN** Agent 进程因错误终止，session 状态为 "error"
- **AND** 用户在 Web UI 对话框输入新指令
- **THEN** 系统将用户消息追加到对话历史，重新调用 Agent 继续执行
- **AND** Agent 带着完整对话历史与新指令继续工作

#### Scenario: 用户中断运行中的 Agent
- **WHEN** Agent 正在运行但用户认为方向错误
- **AND** 用户点击"中断并重试"按钮，输入新指令
- **THEN** 系统取消当前 Agent 任务
- **AND** 以"历史 + 新消息"重新启动 Agent

### Requirement: Agent 可分析页面可点击元素
系统 SHALL 提供 `get_visible_buttons` 工具，返回当前页面所有可点击元素（button/a/[role=button]）的文本与标签信息，供 Agent 自主分析决策。

#### Scenario: 页面无职位信息时 Agent 主动探索
- **WHEN** Agent 导航到官网后发现页面无职位列表
- **THEN** Agent 调用 `get_visible_buttons` 获取所有可点击元素
- **AND** 根据元素文本判断哪个是入口按钮（如"即刻投递"）
- **AND** 调用 `click_element_by_text` 点击该按钮

### Requirement: 通用元素点击工具
系统 SHALL 提供 `click_element_by_text` 工具，Agent 提供文本内容即可点击页面中匹配的可见元素（button/a/[role=button]/input[type=button]）。

#### Scenario: Agent 点击指定文本按钮
- **WHEN** Agent 调用 `click_element_by_text(button_text="即刻投递")`
- **THEN** 系统在页面中查找文本包含"即刻投递"的可点击元素并点击
- **AND** 等待页面加载后返回新页面 URL 与内容摘要

## MODIFIED Requirements

### Requirement: navigate_and_find_positions
导航到招聘官网后，先尝试自动点击常见入口按钮（即刻投递/开始找工作/查看职位/校招岗位等），再提取页面内容与链接。若自动点击未找到入口按钮，在返回信息中列出所有可见按钮供 Agent 后续调用 `click_element_by_text` 决策。
