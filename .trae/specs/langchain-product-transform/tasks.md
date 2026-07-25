# Tasks

## [x] Task 1: Git 分支拆分与管理
- **Priority**: P0
- **Depends On**: None
- **Description**:
  - 从当前 master 分支创建 `openai-agents-sdk` 分支，将该分支上的 LangChain 相关代码（`src/job_application_agent_langchain/`、`tests_langchain/`）删除，仅保留 OpenAI Agents SDK 版本代码（`src/job_application_agent/`、`tests/`）
  - 回到 master 分支，删除 OpenAI Agents SDK 版本代码（`src/job_application_agent/`、`tests/`），仅保留 LangChain/LangGraph 版本代码
  - 同步更新 master 上的 `pyproject.toml`、`requirements.txt`、`README.md`（移除 openai-agents 依赖，补充 langchain/langgraph/deepagents/web 依赖）
  - 从 master checkout 新开发分支 `feature/langchain-product-ui`，后续所有产品化开发在该分支进行
- **Acceptance Criteria**: `openai-agents-sdk` 分支仅含 OpenAI SDK 代码可独立运行；master 仅含 LangChain 代码；`feature/langchain-product-ui` 分支从 master 切出

## [x] Task 2: 引入 deep agents 框架与公司子 Agent 架构重构
- **Priority**: P0
- **Depends On**: [Task 1]
- **Description**:
  - 安装 `deepagents` 依赖，集成到项目
  - 重构 `agents/orchestrator.py`：使用 deep agents harness 编排，为每家公司创建一个子 Agent
  - 新增 `agents/company_agent.py`：实现公司子 Agent，将原 Search Agent（搜索官网、查找岗位、推荐岗位）与 Form Agent（表单填写、投递执行）职责合并到同一子 Agent
  - 迁移原 `agents/search.py` 和 `agents/form.py` 中的工具函数到公司子 Agent 的工具集
  - 移除沙箱相关逻辑，公司子 Agent 直接调用共享 BrowserAutomation
  - 保留并行处理能力：多公司时通过 deep agents 的 sub-agent 机制并行创建多个公司子 Agent
- **Acceptance Criteria**: 单公司完整流程（搜索→推荐→填表→投递）由同一公司子 Agent 完成；多公司可并行；原 search/form 分离节点不再存在

## [x] Task 3: Web UI 后端（FastAPI + WebSocket）
- **Priority**: P0
- **Depends On**: [Task 1]
- **Description**:
  - 新增 `web/` 目录，实现 FastAPI 后端
  - 实现 REST API 端点：
    - `POST /api/sessions` 创建投递会话（接收公司列表、岗位关键词、城市等参数）
    - `POST /api/upload` 文件上传（简历、学历证明、成绩单，分类存储）
    - `GET/PUT /api/settings/notifications` 邮件通知配置读写
    - `GET /api/memory` 查看已记忆的补充信息
    - `POST /api/sessions/{id}/confirm` 用户确认（岗位选择、润色审核、投递确认）
  - 实现 WebSocket 端点 `/ws/sessions/{id}`：实时推送 Agent 执行进度、阶段状态、截图、待确认请求
  - 实现 Agent 执行与 WebSocket 推送的桥接：Agent 的进度事件、人机交互请求通过 WebSocket 推送到前端；前端确认结果回传给 Agent
  - 文件存储管理：按类型分类存储用户上传文件，表单填写时按需匹配
- **Acceptance Criteria**: 后端可启动；WebSocket 能实时推送进度；文件上传分类存储；配置可持久化

## [x] Task 4: Web UI 前端
- **Priority**: P0
- **Depends On**: [Task 3]
- **Description**:
  - 新增 `frontend/` 目录，实现 Web UI 前端（可用 React/Vue 或轻量方案）
  - 实现核心页面/组件：
    - 首页：公司投递任务配置（公司名称、内推码、岗位关键词、期望城市、并行模式）
    - 文件上传区：上传简历 PDF、学历证明、成绩单等
    - 设置页：邮件通知配置（SMTP、发件/收件邮箱、开关）
    - 运行监控页：实时展示 Agent 执行进度（各公司状态、当前阶段、截图）
    - 人机交互面板：岗位选择、简历润色审核（前后对比 + 可编辑）、投递确认
    - 缺失字段批量补充面板：展示所有缺失必填项供用户一次性补充
    - 记忆查看页：展示已记录的补充信息
  - 通过 WebSocket 接收实时进度，通过 REST API 提交配置与确认
- **Acceptance Criteria**: 用户可在浏览器完成全部操作（配置、上传、监控、确认）；人机交互流畅

## [x] Task 5: 基于 JD 的简历自适应润色模块
- **Priority**: P0
- **Depends On**: [Task 2]
- **Description**:
  - 新增 `resume_polish/` 目录，实现简历润色模块
  - 实现 JD 分析：从目标岗位 JD 提取关键要求（技能、经验、关键词）
  - 实现简历内容匹配与提取：从用户大而全的简历中提取与 JD 适配的特色内容
  - 实现 LLM 润色生成：生成针对性简历版本，包括：
    - 针对性自我介绍
    - 重排/强调相关项目经历
    - 突出相关技能
    - 描述中使用 JD 关键术语
  - 实现润色工具函数（@tool），供公司子 Agent 在用户选定岗位后调用
  - 集成到公司子 Agent 流程：用户选岗 → 获取 JD → 调用润色 → UI 展示前后对比 → 用户审核编辑 → 确认内容填入表单
- **Acceptance Criteria**: 能根据 JD 生成润色简历；UI 可展示前后对比并支持编辑；确认后填入表单的是润色内容

## [x] Task 6: 批量缺失字段记忆流程重构
- **Priority**: P0
- **Depends On**: [Task 2, Task 3]
- **Description**:
  - 修改公司子 Agent 表单填写逻辑：遇到简历和记忆中都没有的必填字段时，跳过并加入待询问列表，继续填写其他字段
  - 在所有可填字段填写完成后，通过 WebSocket 推送缺失必填项列表到前端
  - 前端展示批量补充面板，用户一次性补充全部缺失字段
  - 用户补充后，Agent 将内容保存到记忆（learned_fields）并填入表单
  - 复用现有 AgentMemory 的 get_field/set_field/save_memory 机制，确保下次投递自动复用
  - 移除原有的"逐字段 check_field_in_memory interrupt"逻辑
- **Acceptance Criteria**: 缺失字段批量询问（非逐个）；补充内容保存到记忆；下次投递相同字段自动复用

## [x] Task 7: 集成测试与端到端验证
- **Priority**: P1
- **Depends On**: [Task 4, Task 5, Task 6]
- **Description**:
  - 端到端测试：Web UI 启动 → 配置公司 → 上传文件 → Agent 搜索推荐 → 用户选岗 → JD 润色审核 → 表单填写 → 批量补充缺失字段 → 投递确认
  - 多公司并行处理测试
  - 记忆持久化测试：补充字段后重启，下次投递自动复用
  - 邮件通知配置生效测试
  - 更新 README 文档说明新的 Web UI 启动方式与使用流程
- **Acceptance Criteria**: 端到端流程跑通；记忆持久化生效；文档清晰

# Task Dependencies
- [Task 2] depends on [Task 1]
- [Task 3] depends on [Task 1]
- [Task 4] depends on [Task 3]
- [Task 5] depends on [Task 2]
- [Task 6] depends on [Task 2, Task 3]
- [Task 7] depends on [Task 4, Task 5, Task 6]
