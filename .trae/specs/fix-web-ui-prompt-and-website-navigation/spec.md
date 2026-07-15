# Web UI 实时对话与官网导航增强 Spec

## Why
用户实际使用 Agent 投递小鹏汽车校招时发现三个问题：(1) Agent 遇到问题终止或运行中卡住时，用户只能在命令行给它新 prompt，Web UI 无法实时干预；(2) 小鹏汽车校招官网登录后初始页面没有职位列表，需要点击"即刻投递"等入口按钮才能看到岗位，Agent 不会自动识别并点击这些按钮，需要用户手动指导；(3) Agent 找到岗位、用户确认后开始填表前，需要先登录或注册，但当前 Agent 没有引导用户登录的意识，且用户必须在 Agent 使用的同一浏览器实例中完成登录（否则登录态无法被 Agent 复用），扫码登录等场景尤其需要用户自行操作。

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
- **用户自行登录/注册引导**：用户确认岗位后、填表前，Agent 引导用户在**同一浏览器实例**中完成登录或注册
  - Agent 以非 headless 模式启动浏览器（用户可见浏览器窗口），导航到登录页后暂停
  - 通过 Web UI 弹出登录请求：提示用户"请在弹出的浏览器窗口中完成登录（支持扫码/验证码），完成后点击此按钮"
  - 用户在 Agent 的浏览器窗口中自行登录/注册（扫码、短信验证码、账号密码均可）
  - 用户点击"已完成登录"后，Agent 检测登录状态，确认后继续填表
  - 新增 `request_user_login` HITL 工具与 `check_login_status` 检测工具

## Impact
- Affected code:
  - `src/job_application_agent_langchain/web/session_manager.py` — 存储对话历史，支持续接与中断
  - `src/job_application_agent_langchain/web/routes.py` — 新增消息发送与中断端点
  - `src/job_application_agent_langchain/web/app.py` — WebSocket 处理 user_message
  - `src/job_application_agent_langchain/web/static/js/app.js` — 前端对话 UI、中断按钮、登录确认 UI
  - `src/job_application_agent_langchain/web/static/index.html` — 对话区域与登录确认 HTML
  - `src/job_application_agent_langchain/web/static/css/style.css` — 对话区域与登录确认样式
  - `src/job_application_agent_langchain/agent_events.py` — 新增 request_user_login 抽象方法
  - `src/job_application_agent_langchain/web/emitter.py` — 实现 request_user_login
  - `src/job_application_agent_langchain/agents/company_agent.py` — 传递历史消息、登录流程工具、更新系统提示
  - `src/job_application_agent_langchain/agents/search.py` — 增强导航、新增工具
  - `src/job_application_agent_langchain/browser/automation.py` — 非 headless 模式、按文本点击、获取可见按钮、登录检测

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

### Requirement: 用户自行登录/注册引导
系统 SHALL 在用户确认岗位后、开始填表前，引导用户在 Agent 使用的**同一浏览器实例**中完成登录或注册。Agent 以非 headless 模式启动浏览器，用户可直接在弹出的浏览器窗口中操作（支持扫码、短信验证码、账号密码等任意登录方式）。

#### Scenario: 填表前引导用户登录
- **WHEN** 用户确认岗位，Agent 准备开始填表
- **AND** Agent 检测到当前页面需要登录（存在登录入口或表单提交被拦截到登录页）
- **THEN** Agent 通过 `request_user_login` 工具在 Web UI 弹出登录请求
- **AND** 请求中包含当前登录页 URL，提示用户"请在弹出的浏览器窗口中完成登录（支持扫码/验证码），完成后点击此按钮"
- **AND** Agent 暂停等待用户在 Web UI 点击"已完成登录"

#### Scenario: 用户未注册需先注册
- **WHEN** Agent 引导用户登录，但用户没有账号需要注册
- **THEN** 用户可在同一浏览器窗口中自行点击"注册"按钮完成注册
- **AND** 注册完成后同样点击"已完成登录"按钮，Agent 继续检测登录状态

#### Scenario: Agent 验证登录状态
- **WHEN** 用户点击"已完成登录"后
- **THEN** Agent 调用 `check_login_status` 检测当前页面是否已登录
- **AND** 检测方式：页面是否仍含"登录"/"注册"按钮、URL 是否仍为登录页、是否有用户头像/用户名等登录态标识
- **AND** 若已登录，继续填表流程；若未登录，提示用户重新登录

## MODIFIED Requirements

### Requirement: navigate_and_find_positions
导航到招聘官网后，先尝试自动点击常见入口按钮（即刻投递/开始找工作/查看职位/校招岗位等），再提取页面内容与链接。若自动点击未找到入口按钮，在返回信息中列出所有可见按钮供 Agent 后续调用 `click_element_by_text` 决策。

### Requirement: 浏览器启动模式
浏览器以**非 headless** 模式启动，确保用户可看到并直接操作 Agent 使用的浏览器窗口（登录、扫码等场景需要用户在同一浏览器实例中操作）。

### Requirement: 公司子 Agent 工作流程
在阶段 3（简历润色）与阶段 4（填表）之间新增"用户登录/注册"步骤：Agent 导航到登录页后调用 `request_user_login` 暂停等待用户登录，用户在 Web UI 确认后 Agent 调用 `check_login_status` 验证登录态，通过后继续填表。
