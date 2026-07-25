# Tasks

- [x] Task 1: 后端 - 对话历史存储与续接/中断机制
  - **Priority**: P0
  - **Description**:
    - 修改 `session_manager.py`：SessionInfo 新增 `message_history: list` 与 `pending_user_messages: list` 字段
    - 修改 `company_agent.py` 的 `run_company_agent`：接收可选 `message_history` 参数，调用 Agent 时传入完整历史，返回时输出完整 messages 列表
    - 修改 `orchestrator.py`：透传 message_history
    - 在 `session_manager.py` 新增 `send_message(session_id, user_message)` 方法：
      - 若 Agent 运行中：消息加入 pending_user_messages 队列，当前 ainvoke 完成后自动续接
      - 若 Agent 已完成/出错：追加用户消息到历史，立即重新启动 Agent 任务
    - 在 `session_manager.py` 新增 `interrupt_and_restart(session_id, user_message)` 方法：取消当前任务，追加消息，重新启动
    - 修改 `_run_agent`：ainvoke 返回后检查 pending_user_messages，有则自动续接
    - Agent 最终消息通过 push_event 推送 `agent_message` 事件给前端
    - 在 `routes.py` 新增 `POST /api/sessions/{id}/message` 与 `POST /api/sessions/{id}/interrupt` 端点
    - 在 `app.py` WebSocket 处理中新增 `user_message` 与 `interrupt` 消息类型
  - **Acceptance Criteria**: Agent 任意状态下用户发消息均可续接；运行中可中断重试；对话历史完整保留

- [x] Task 2: 前端 - 对话 UI 与中断按钮
  - **Priority**: P0
  - **Depends On**: [Task 1]
  - **Description**:
    - 在 `index.html` 监控页面新增对话区域：消息列表 + 输入框 + 发送按钮 + 中断重试按钮
    - 在 `app.js` 新增对话消息发送（WebSocket/REST）与接收（agent_message 事件）逻辑
    - 对话区域始终可见且可输入（运行中也可发送，消息排队）
    - 中断按钮在 Agent 运行中显示，点击后弹出输入框让用户输入新指令
    - 用户消息右对齐，Agent 回复左对齐，区分样式
    - 发送消息后输入框清空，支持回车发送
    - 在 `style.css` 新增对话区域样式
  - **Acceptance Criteria**: 用户可随时发送消息；Agent 回复可见；中断按钮可取消并重启 Agent

- [x] Task 3: 浏览器自动化与搜索工具增强
  - **Priority**: P0
  - **Description**:
    - 修改 `automation.py` 浏览器启动：默认以**非 headless** 模式启动，确保用户可见并操作浏览器窗口
    - 在 `automation.py` 新增 `click_element_by_text(text: str) -> dict` 方法：查找 button/a/[role=button]/input[type=button] 中文本包含指定内容的可见元素并点击，返回 {success, new_url, page_text_summary}
    - 在 `automation.py` 新增 `get_visible_buttons() -> list[dict]` 方法：返回页面所有可见可点击元素的 {text, tag, href, role} 列表
    - 在 `automation.py` 新增 `check_login_status() -> dict` 方法：检测当前页面登录状态（是否含登录/注册按钮、URL 是否为登录页、是否有用户头像/用户名），返回 {logged_in, indicators}
    - 在 `search.py` 新增 `@tool click_element_by_text_tool(button_text: str)` 工具
    - 在 `search.py` 新增 `@tool get_visible_buttons_tool()` 工具
    - 在 `search.py` 新增 `@tool check_login_status_tool()` 工具
    - 增强 `navigate_and_find_positions`：导航后自动尝试点击常见入口按钮（即刻投递/开始投递/投递简历/查看职位/开始找工作/校招岗位/校园招聘/进入投递/我要投递/投递入口/搜索职位/职位搜索），点击后等待加载再提取内容；未找到则在返回信息中列出所有可见按钮
    - 三个新工具加入 `get_search_tools()` 返回列表
  - **Acceptance Criteria**: Agent 可调用工具查看页面按钮并点击；navigate_and_find_positions 能自动点击入口按钮；浏览器非 headless 模式用户可见

- [x] Task 4: 登录/注册引导 HITL 机制
  - **Priority**: P0
  - **Depends On**: [Task 3]
  - **Description**:
    - 在 `agent_events.py` 的 `AgentEventEmitter` 新增抽象方法 `request_user_login(request_id, login_url, message) -> str`：阻塞等待用户完成登录确认，返回 "logged_in" 或 "retry"
    - 在 `agent_events.py` 的 `CLIEmitter` 实现 `request_user_login`：终端提示用户登录后按回车
    - 在 `web/emitter.py` 的 `WebEventEmitter` 实现 `request_user_login`：推送 user_login 请求事件，await future 等待用户点击"已完成登录"
    - 在 `company_agent.py` 新增 `@tool request_user_login(login_url: str) -> str` 工具：调用 emitter.request_user_login，返回登录结果
    - 前端 `app.js` 新增 user_login 请求处理：弹出登录确认面板，展示登录页 URL，"已完成登录"与"重新检测"按钮
    - 前端 `index.html` 新增登录确认面板 HTML
    - 前端 `style.css` 新增登录确认面板样式
    - WebSocket 处理 user_login 响应类型
  - **Acceptance Criteria**: Agent 可通过 Web UI 引导用户登录；用户在浏览器窗口登录后点击确认；Agent 检测登录态后继续

- [x] Task 5: 系统提示更新与测试
  - **Priority**: P1
  - **Depends On**: [Task 1, Task 3, Task 4]
  - **Description**:
    - 更新 `company_agent.py` 的 `_build_system_prompt`：
      - 阶段 1 搜索部分新增指导：导航到官网后若页面无职位信息，调用 `get_visible_buttons_tool` 查看可点击元素，再调用 `click_element_by_text_tool` 点击入口按钮（如即刻投递/开始找工作）
      - 在阶段 3（简历润色）与阶段 4（填表）之间新增"用户登录/注册"步骤：导航到登录页后调用 `request_user_login` 暂停等待用户登录，用户确认后调用 `check_login_status_tool` 验证登录态，通过后继续填表
      - 新增"用户指导"说明：用户可能在运行中发送指导消息，需遵循用户指令调整行为
    - 新增测试：对话续接测试、中断重启测试、入口按钮工具测试、登录引导测试
    - 运行全部测试确保无回归
  - **Acceptance Criteria**: 全部测试通过，系统提示包含入口按钮探索、登录引导与用户指导说明

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 4] depends on [Task 3]
- [Task 5] depends on [Task 1, Task 3, Task 4]
