# LangChain Agent 产品化与简历自适应润色 Spec

## Why
当前仓库在 master 分支中混杂了两套框架实现（OpenAI Agents SDK 与 LangChain/LangGraph），结构混乱。同时现有 Agent 仅为命令行工具，无法作为产品交付；架构上按"搜索/表单"拆分子 Agent 过于冗余，且缺少根据岗位 JD 自适应润色简历的核心能力。需要：拆分分支、构建 Web UI、重构为"每公司一个子 Agent"架构、新增基于 JD 的简历自适应润色功能。

## What Changes
- **分支拆分**：新建 `openai-agents-sdk` 分支，将 OpenAI Agents SDK 版本代码全部迁移至该分支；master 仅保留 LangChain/LangGraph 实现；从 master checkout 新开发分支进行后续产品化开发
- **Web UI 界面**：基于 FastAPI 后端 + 前端的 Web 应用，支持文件上传（简历、学历证明、成绩单）、邮件通知配置、实时进度展示、人机交互确认
- **引入 deep agents 框架**：使用 deepagents 库作为 harness，提供 sub-agent 编排、文件式记忆与内置工具系统
- **架构重构**：**BREAKING** 废弃原有的"搜索 Agent + 表单 Agent"分离架构，改为"每家公司创建一个子 Agent"，将搜索官网、岗位查找、表单填写、投递执行合并到同一个公司子 Agent 中；不使用沙箱
- **基于 JD 的简历自适应润色**：找到用户投递的目标岗位后，根据该岗位 JD，从用户大而全的简历中提取适配内容进行强调突出，生成针对性简历版本，经用户在 UI 中审核编辑后填入表单
- **批量缺失字段询问**：**BREAKING** 修改原"逐字段 interrupt 询问"的记忆流程，改为表单填写阶段先尽力填完所有能填字段，收集全部缺失必填项，填写完成后一次性批量询问用户，用户补充后保存到记忆，下次投递自动复用

## Impact
- Affected specs: `job_application_agent`（原 Spec 文档仅作参考，本 Spec 取代其架构与功能定义）
- Affected code:
  - `src/job_application_agent/`（OpenAI SDK 版，迁移至新分支）
  - `src/job_application_agent_langchain/`（LangChain 版，保留在 master 并在开发分支上重构）
  - 新增 `src/job_application_agent_langchain/web/`（Web UI 后端）
  - 新增 `src/job_application_agent_langchain/frontend/`（Web UI 前端）
  - 新增 `src/job_application_agent_langchain/agents/company_agent.py`（公司子 Agent）
  - 新增 `src/job_application_agent_langchain/resume_polish/`（简历润色模块）
  - 重构 `agents/orchestrator.py`、`agents/search.py`、`agents/form.py`（合并为公司子 Agent）

## ADDED Requirements

### Requirement: Web UI 界面
系统 SHALL 提供 Web UI 界面，将 Agent 从命令行工具转变为可交互的产品。Web UI 基于 FastAPI 后端 + 前端实现，通过 WebSocket 实时推送 Agent 执行进度。

#### Scenario: 用户通过 Web UI 启动投递
- **WHEN** 用户在浏览器打开 Web UI，填写公司名称、岗位关键词、期望城市等参数并提交
- **THEN** 后端启动 Agent 流程，前端实时展示执行进度（搜索官网、查找岗位、填写表单等阶段状态）

#### Scenario: 文件上传
- **WHEN** 用户在 Web UI 上传简历 PDF、学历证明、成绩单等文件
- **THEN** 系统保存文件到本地存储目录，并在后续表单填写时按需使用对应文件

#### Scenario: 邮件通知配置
- **WHEN** 用户在 Web UI 设置界面配置 SMTP 服务器、发件邮箱、收件邮箱等参数并开关邮件通知
- **THEN** 系统保存配置，Agent 运行时按配置发送邮件通知

#### Scenario: 人机交互确认
- **WHEN** Agent 进入需要用户决策的节点（岗位选择、简历润色审核、投递确认）
- **THEN** Web UI 弹出交互面板，用户做出选择后 Agent 继续执行

### Requirement: Deep Agents 框架 Harness
系统 SHALL 引入 deepagents 框架作为 Agent 编排 harness，利用其 sub-agent 编排、文件式记忆与内置工具系统简化多公司并行处理。

#### Scenario: 使用 deep agents 编排公司子 Agent
- **WHEN** 用户提交多家公司的投递任务
- **THEN** 系统使用 deep agents 的 sub-agent 机制为每家公司创建一个子 Agent，并行或顺序执行投递流程

### Requirement: 每公司一个子 Agent
系统 SHALL 为每家公司创建一个子 Agent，该子 Agent 负责完成该公司的全部投递工作，包括搜索官网、查找岗位、填写注册表单、填写简历表单、执行投递。不再为每个环节单独创建子 Agent，不使用沙箱。

#### Scenario: 单公司完整投递流程
- **WHEN** 公司子 Agent 启动处理某家公司
- **THEN** 该子 Agent 依次完成：搜索官网 → 查找岗位 → 推荐岗位 → 等待用户选择 → JD 简历润色 → 填写表单 → 批量询问缺失字段 → 等待用户投递确认 → 执行投递，全流程在同一子 Agent 内完成

#### Scenario: 多公司并行处理
- **WHEN** 用户提交多家公司并选择并行模式
- **THEN** 系统为每家公司创建独立子 Agent 并行执行，各子 Agent 间状态隔离

### Requirement: 基于 JD 的简历自适应润色
系统 SHALL 在用户选定目标岗位后，根据该岗位的 JD（职位描述），从用户大而全的简历中提取适配该岗位的特色内容进行强调突出，生成针对性简历版本，提升求职者竞争力。润色流程为"LLM 动态润色 + 用户在 UI 审核编辑"两者结合。

#### Scenario: 根据岗位 JD 润色简历
- **WHEN** 用户选定某公司的目标岗位后，系统获取该岗位的完整 JD
- **THEN** 系统使用 LLM 分析 JD 要求与用户简历内容的匹配度，生成润色后的简历内容，包括：
  1. 针对性自我介绍（突出与岗位匹配的背景）
  2. 重新排序/强调与岗位相关的项目经历
  3. 突出与岗位相关的技能
  4. 在描述中使用 JD 中的关键术语

#### Scenario: 用户审核润色结果
- **WHEN** 系统生成润色后的简历内容
- **THEN** Web UI 展示润色前后对比（原版 vs 润色版），用户可编辑修改润色内容
- **AND** 用户确认后，系统将确认的内容填入该公司表单

#### Scenario: 润色内容填入表单
- **WHEN** 用户确认润色后的简历内容
- **THEN** 公司子 Agent 将润色后的内容（而非原始简历内容）填入表单对应字段

### Requirement: 文件管理服务
系统 SHALL 提供文件管理服务，支持用户通过 Web UI 上传简历 PDF、学历证明、成绩单等文件，并在表单填写时按需调用。

#### Scenario: 上传与使用文件
- **WHEN** 用户上传简历、学历证明、成绩单等文件
- **THEN** 系统按类型分类存储，表单填写时遇到对应上传需求自动匹配并上传相应文件

## MODIFIED Requirements

### Requirement: 批量缺失字段记忆流程
系统 SHALL 修改原"逐字段 interrupt 询问"的记忆流程。表单填写阶段，Agent 先尽力填完所有能从简历和记忆中获取的字段，同时收集全部缺失的必填项；在完成所有可填字段的填写后，一次性批量询问用户所有缺失必填项；用户补充后保存到记忆，下次投递自动复用。

#### Scenario: 批量收集并询问缺失字段
- **WHEN** 公司子 Agent 在表单填写过程中遇到简历和记忆中都没有的必填字段（如身份证号）
- **THEN** Agent 跳过该字段继续填写其他字段，将该缺失必填项加入待询问列表
- **AND** 当所有可填字段填写完成后，Agent 通过 Web UI 一次性展示所有缺失必填项，请用户补充
- **WHEN** 用户补充全部缺失字段
- **THEN** 系统将补充内容保存到记忆（learned_fields），并填入表单对应字段

#### Scenario: 记忆复用避免重复询问
- **WHEN** 用户在某次投递中补充了某字段的值并保存到记忆
- **THEN** 后续投递遇到相同字段时，Agent 直接从记忆中取值填入，不再询问用户

### Requirement: 架构简化
系统 SHALL 将原有的 Search Agent Node 与 Form Agent Node 合并为单一的公司子 Agent。原 LangGraph StateGraph 中的 search、form、human_in_loop 节点职责整合到公司子 Agent 内部，由 deep agents harness 编排。

## REMOVED Requirements

### Requirement: 分离的搜索 Agent 与表单 Agent
**Reason**: 原架构按环节拆分子 Agent 过于冗余，每家公司需要跨多个 Agent 传递状态，增加复杂度
**Migration**: 合并为每公司一个子 Agent，搜索官网、岗位查找、表单填写、投递执行由同一子 Agent 完成

### Requirement: 沙箱执行环境
**Reason**: 用户明确指出不必使用沙箱，公司子 Agent 直接在主环境中使用 Playwright 浏览器自动化即可
**Migration**: 公司子 Agent 直接调用共享的 BrowserAutomation 服务，不引入沙箱隔离层
