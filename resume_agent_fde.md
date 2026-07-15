# 个人简历

## 个人信息

| 项目 | 内容 |
|------|------|
| 姓名 | （请填写） |
| 邮箱 | （请填写） |
| 电话 | （请填写） |
| GitHub | （请填写） |
| 工作年限 | （请填写） |

---

## 求职意向

**目标岗位**：Agent 开发工程师 / Forward Deployed Engineer (FDE)

**期望城市**：（请填写）

---

## 专业技能

- **AI Agent 框架**：熟练掌握 LangChain + LangGraph 技术栈，精通 `StateGraph` 图编排（节点定义、条件路由、checkpoint 持久化），`ChatOpenAI` 模型调用与 `bind_tools` 工具绑定，`@tool` 装饰器自定义工具函数，`MemorySaver` 状态持久化
- **Multi-Agent 架构设计**：具备完整的 Multi-Agent 系统设计经验，能独立设计状态机驱动的多节点协作架构，实现 Orchestrator 协调 + Search Agent + Form Agent 三层分工，构建 Human-in-the-loop 交互模式
- **LLM 集成与 Prompt Engineering**：熟悉 OpenAI 兼容 API 调用，具备动态 System Prompt 构建能力，能根据上下文注入用户信息、记忆数据、公司列表等多维度信息，实现上下文感知的 Agent 行为
- **浏览器自动化**：精通 Playwright（Chromium），掌握反检测技术（隐藏 WebDriver 标记、UA 伪装、AutomationControlled 禁用），能处理文本框、下拉框、日历组件、文件上传等复杂表单操作，内置搜索引擎策略（Bing/DuckDuckGo）
- **Python 工程化**：熟悉 Python 3.12+ 异步编程（asyncio），Pydantic 数据建模与校验，python-dotenv 配置管理，pytest 单元测试，setuptools/pyproject.toml 项目构建
- **持久化与记忆系统**：具备 Agent 记忆系统设计经验，能实现跨会话的字段级记忆持久化（JSON 存储），支持双层查询优先级（learned > source）
- **跨平台通知系统**：掌握 plyer 跨平台桌面通知，SMTP 邮件通知，无桌面环境（Linux SSH）优雅降级方案
- **其他**：Git 版本控制，Conda 环境管理，RESTful API 设计，正则表达式

---

## 项目经历

### 校招简历自动投递 Agent（LangChain + LangGraph 实现）

**时间**：2025.06 - 至今

**项目概述**：基于 LangChain + LangGraph 框架的 AI Agent 自动化简历投递工具，解决校招/社招/实习网申中重复填写表单、筛选岗位的繁琐工作。采用 LangGraph StateGraph 图编排架构，支持多公司并行处理、持久化记忆、Human-in-the-loop 交互，能够自动搜索招聘官网、推荐岗位、填写简历表单并完成投递。

**技术栈**：Python 3.12+ · LangChain · LangGraph (StateGraph / MemorySaver) · ChatOpenAI · Playwright · Pydantic · asyncio · plyer · SMTP

**核心工作**：

**1. LangGraph StateGraph 图编排架构设计**

- 使用 LangGraph `StateGraph` 构建 4 节点工作流：`orchestrator`（编排协调）→ `search`（岗位搜索）→ `form`（表单填写）→ `human_in_loop`（人工确认）
- 设计 `router_node` 条件路由函数，根据 `current_phase` 状态机（共 8 个状态：start → search → search_complete → wait_user_register → user_ready → form → form_complete → delivery_confirm → delivery_done → end）动态路由到不同处理节点
- 使用 `add_conditional_edges` + `add_edge` 构建回环拓扑：search/form/human_in_loop 节点完成后回到 orchestrator，由 orchestrator 推进状态机并再次路由
- 集成 `MemorySaver()` checkpointer，为每个公司分配独立 `thread_id`，支持状态持久化与断点续传

**2. LangChain Tool 绑定与 Agent 工具系统**

- 使用 `llm.bind_tools(tools)` 模式将 15 个自定义工具函数绑定到不同 Agent 节点
- **Search Agent 工具集**（5 个）：`search_company_website`（搜索引擎搜索官网）、`navigate_and_find_positions`（导航+查找岗位）、`find_max_positions`（查询最大可投递数）、`get_position_details`（获取岗位详情）、`notify_user`（通知用户）
- **Form Agent 工具集**（10 个）：`upload_resume`（简历上传）、`fill_form_field`（支持 text/select/radio/checkbox/date/textarea 6 种表单元素）、`check_field_in_memory`（记忆查询）、`get_current_page_form`（表单字段识别）、`submit_application`（投递执行）、`take_screenshot_for_review`（截图审查）等
- 所有工具使用 `@tool`（`langchain_core.tools.tool`）装饰器定义，异步浏览器操作通过 `asyncio.get_event_loop().run_until_complete()` 桥接为同步执行

**3. 持久化记忆系统（AgentMemory）**

- 设计 `AgentMemory` Pydantic 模型，包含 4 个核心字段：`source_user_info`（文档解析的原始信息）、`learned_fields`（运行时补充的字段）、`field_metadata`（含时间戳和原因）、`company_history`（投递历史）
- 实现 `get_field(field_name)` 双层查询：优先从 `learned_fields` 取值，回退到 `source_user_info`
- 实现 `set_field(field_name, value, reason)` 记录用户补充字段，自动附带时间戳
- 集成 `check_field_in_memory` 工具：Form Agent 遇到必填字段缺失时，自动查询记忆 → 若有值直接填写 → 若无值则通过 `ask_user_for_field` 工具询问用户并记录，下次运行自动复用
- 记忆数据通过 `load_memory()` / `save_memory()` 持久化到本地 JSON 文件，启动时自动加载，结束时自动保存，数据不上传云端

**4. Human-in-the-loop 交互设计**

- 在岗位搜索完成（`wait_user_register`）和投递前（`delivery_confirm`）两个关键节点设置人工确认点
- 通过 `notify_user` 工具的 `need_confirmation` 参数实现终端 `input()` 阻塞等待，用户确认后推进状态机
- 投递确认点弹出醒目警告，提醒用户投递后不可修改志愿，支持用户选择"AI 自动投递"或"手动投递"

**5. Playwright 浏览器自动化模块**

- 封装 `BrowserAutomation` 单例类，通过 `asyncio.Lock` 保证线程安全，管理 Chromium 浏览器生命周期
- 实现反检测措施：注入 JS 隐藏 `navigator.webdriver`、自定义中文 User-Agent、禁用 `AutomationControlled` 特性、设置 1920x1080 viewport
- 支持多搜索引擎搜索（Bing/DuckDuckGo），内置验证码检测和自动切换机制
- 提供完整的表单操作 API：`fill_text`、`select_option`、`click_radio`、`click_checkbox`、`select_date_from_calendar`（支持 Ant Design / Element UI 日历组件）、`upload_file`、`get_form_fields`（自动识别页面表单元素及 label/placeholder/options）

**6. 跨平台通知系统**

- 设计三层通知机制：终端打印（全平台）+ 系统托盘弹窗（Windows/macOS 通过 plyer）+ 邮件通知（SMTP，可选）
- 通过 `DISPLAY`/`WAYLAND_DISPLAY` 环境变量检测桌面环境，Linux SSH 服务器自动降级为纯终端通知
- 邮件通知支持 `.env` 配置开关，所有通知通道并行执行

**7. 工程化实践**

- 使用 Pydantic 定义 `UserInfo` 数据模型（含基础信息、教育经历、实习/项目经历、技能等），实现 TXT 格式个人信息解析器（支持 Markdown 风格章节、字段映射）
- 使用 `python-dotenv` 管理配置，通过 `Settings` 单例 + `pydantic-settings` 校验，覆盖 API Key、模型名称、浏览器模式、邮件配置、记忆文件路径等
- 编写 pytest 单元测试覆盖配置、解析、Agent 创建、数据模型等模块
- 支持顺序和并行两种运行模式，并行模式下通过 `asyncio.gather` 实现多公司同时处理

**项目亮点**：
- 完整覆盖 LangChain + LangGraph 技术栈，从 StateGraph 构建、条件路由、工具绑定到 checkpoint 持久化
- 自研 Agent 记忆系统，实现跨会话的字段级信息持久化，体现对 Agent 长期记忆问题的深入思考
- 16 个自定义 Tool 函数覆盖搜索、表单填写、记忆管理、通知四大领域，体现了系统性工具设计能力
- 浏览器自动化 + 反检测方案，展现了对 Web 技术和反爬机制的深入理解
- 状态机驱动的图编排架构，节点职责清晰，具备良好的可扩展性

---

## 教育背景

| 项目 | 内容 |
|------|------|
| 学校 | （请填写） |
| 学历 | （请填写） |
| 专业 | （请填写） |
| 毕业时间 | （请填写） |

---

## 补充说明

- 本简历聚焦 **LangChain + LangGraph** 技术栈，适合投递要求 LangChain 经验的 Agent 开发岗位
- 投递 Agent 开发工程师时，可强调：StateGraph 图编排、Conditional Routing、Tool 系统设计、Memory 持久化
- 投递 FDE 岗位时，可强调：浏览器自动化、反检测、跨平台兼容、端到端系统集成、工程化落地能力