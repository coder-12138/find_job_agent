# 自动校招简历投递Agent - Implementation Plan

## [ ] Task 1: Conda环境创建与项目初始化
- **Priority**: P0
- **Depends On**: None
- **Description**: 
  - 创建专门的conda环境
  - 初始化Python项目
  - 配置项目依赖（`langchain`, `langgraph`, Playwright, python-dotenv, plyer等）
  - 设置项目结构
  - 创建.env模板文件
- **Acceptance Criteria Addressed**: [AC-12]
- **Test Requirements**:
  - `programmatic` TR-1.1: 能成功创建conda环境
  - `programmatic` TR-1.2: 项目能成功安装所有依赖（包括 `langchain`, `langgraph`）
  - `programmatic` TR-1.3: 项目结构符合规范
  - `programmatic` TR-1.4: .env模板文件创建成功
- **Notes**: 使用Playwright作为浏览器自动化工具，使用plyer实现跨平台通知

## [ ] Task 2: 用户信息管理模块 + 记忆存储模块
- **Priority**: P0
- **Depends On**: [Task 1]
- **Description**: 
  - 实现用户简历和个人信息的读取与存储
  - 支持多种格式的简历解析
  - 设计用户输入交互界面
  - 实现信息缺失标记功能
  - **实现记忆存储模块（核心新增功能）**：
    - 设计 `AgentMemory` 数据结构（`source_user_info`, `learned_fields`, `field_metadata`, `company_history`）
    - 实现 `get_field(field_name)` 方法：优先从 `learned_fields` 查找，再从 `source_user_info` 查找
    - 实现 `set_field(field_name, value, reason)` 方法：记录用户补充的字段，附带时间戳和原因
    - 实现本地持久化存储（JSON 或 SQLite），保存路径为项目目录下的 `data/memory.json`
    - 实现记忆加载功能，Agent 启动时自动加载已有记忆
    - 提供命令行接口让用户查看已记录的补充信息
- **Acceptance Criteria Addressed**: [AC-1, AC-6, AC-6b, AC-6c, AC-19]
- **Test Requirements**:
  - `programmatic` TR-2.1: 能成功读取用户提供的信息文档
  - `programmatic` TR-2.2: 能正确存储和检索用户信息
  - `programmatic` TR-2.3: 能正确标记缺失信息
  - `programmatic` TR-2.4: `get_field` 能正确优先返回 `learned_fields` 中的值
  - `programmatic` TR-2.5: `set_field` 能正确记录字段并附带元数据
  - `programmatic` TR-2.6: 记忆数据能正确持久化到本地文件
  - `programmatic` TR-2.7: Agent 重启后能正确加载之前的记忆
  - `human-judgement` TR-2.8: 用户输入界面清晰易用

## [ ] Task 3: LangGraph 多 Agent 基础框架搭建（Orchestrator + 通知 Tool + Memory）
- **Priority**: P0
- **Depends On**: [Task 1, Task 2]
- **Description**: 
  - 集成 `langchain` 和 `langgraph` 包
  - 定义 LangGraph `StateGraph` 的状态结构（`AgentState`）
  - 实现 Orchestrator Node（协调主节点）
    - 接收用户输入，管理全局状态
    - 协调各子节点工作流
  - 实现 Router Node（路由节点）
    - 根据当前状态决定下一步执行哪个节点
  - **实现 Human-in-the-loop Node**：
    - 使用 LangGraph 的 `interrupt` 机制暂停执行
    - 等待用户输入（岗位选择、信息补充、投递确认等）
    - 用户输入后恢复执行
  - **实现 Memory Update Node**：
    - 用户回答缺失字段后，调用 `set_field` 记录到记忆存储
    - 自动触发记忆持久化保存
  - **实现通知 Tool**：
    - 封装终端打印通知（全平台，始终可用）
    - 封装Windows/macOS系统弹窗通知（使用plyer库，一套代码支持两个平台）
    - 实现无桌面环境检测与优雅降级（Linux SSH环境自动跳过弹窗）
    - 实现邮件通知功能（可选开启/关闭，全平台可用）
    - 在.env中配置邮件发送参数（发件邮箱、SMTP服务器、密码等）
    - 支持用户确认输入（当需要用户决策时）
  - 实现.env配置读取
- **Acceptance Criteria Addressed**: [AC-1, AC-7, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-19]
- **Test Requirements**:
  - `programmatic` TR-3.1: LangGraph StateGraph 能成功构建和编译
  - `programmatic` TR-3.2: Orchestrator Node 能成功初始化并管理状态
  - `programmatic` TR-3.3: Router Node 能正确根据状态路由到目标节点
  - `programmatic` TR-3.4: Human-in-the-loop Node 能正确 interrupt 并恢复
  - `programmatic` TR-3.5: Memory Update Node 能正确调用 `set_field` 并持久化
  - `programmatic` TR-3.6: 通知 Tool 能正确处理终端打印
  - `programmatic` TR-3.7: 通知 Tool 的Windows/macOS系统弹窗通知代码实现正确（使用plyer库，平台检测逻辑正确）
  - `programmatic` TR-3.8: 通知 Tool 在无桌面环境的Linux上降级为终端通知，不报错
  - `programmatic` TR-3.9: 通知 Tool 能成功发送邮件到指定邮箱（如果配置）
  - `programmatic` TR-3.10: 通知 Tool 能通过.env控制邮件通知的开关
  - `programmatic` TR-3.11: Agent能正确读取.env配置
  - `programmatic` TR-3.12: Agent遇到未知问题时能正确暂停并调用通知 Tool 询问用户

## [ ] Task 4: 浏览器自动化模块（Playwright）
- **Priority**: P0
- **Depends On**: [Task 1]
- **Description**: 
  - 集成Playwright浏览器自动化
  - 实现网页导航、元素定位、表单填写等基础功能
  - 支持下拉菜单选择、单选按钮点击、复选框勾选
  - 支持日历组件选择日期
  - 支持文件上传
- **Acceptance Criteria Addressed**: [AC-2, AC-4, AC-5, AC-7]
- **Test Requirements**:
  - `programmatic` TR-4.1: 能成功启动浏览器并导航到指定URL
  - `programmatic` TR-4.2: 能正确定位和填写文本框
  - `programmatic` TR-4.3: 能正确选择下拉菜单选项
  - `programmatic` TR-4.4: 能正确点击单选按钮和勾选复选框
  - `programmatic` TR-4.5: 能使用日历组件选择日期（精确到月或日）
  - `programmatic` TR-4.6: 能成功上传文件

## [ ] Task 5: Search Agent Node 实现
- **Priority**: P0
- **Depends On**: [Task 3, Task 4]
- **Description**: 
  - 实现 Search Agent Node（LangGraph 节点）
  - 集成浏览器自动化工具
  - 集成通知 Tool（可随时调用通知用户）
  - 实现公司招聘官网搜索功能
  - 实现自动导航到招聘官网
  - 实现岗位搜索功能
  - 实现岗位匹配算法（基于JD和用户简历）
  - 实现可投递岗位数查询功能
  - 生成岗位推荐信息，每个岗位包含：
    - 岗位名称
    - 工作地点
    - 完整 Job Description
    - 推荐理由（基于用户简历和岗位要求的匹配度分析）
  - 返回2n个推荐岗位供用户选择
  - 完成后调用通知 Tool 通知用户
- **Acceptance Criteria Addressed**: [AC-2, AC-3]
- **Test Requirements**:
  - `programmatic` TR-5.1: Search Agent Node 能成功集成到 StateGraph
  - `programmatic` TR-5.2: 能通过搜索引擎找到目标公司的招聘官网
  - `programmatic` TR-5.3: 能成功导航到招聘官网
  - `programmatic` TR-5.4: 能搜索到符合条件的岗位
  - `programmatic` TR-5.5: 能正确返回2n个推荐岗位
  - `programmatic` TR-5.6: 每个岗位包含岗位名称、工作地点、完整JD、推荐理由
  - `programmatic` TR-5.7: 能正确调用通知 Tool 通知用户
  - `programmatic` TR-5.8: 能与 Orchestrator Node 正确协作
  - `human-judgement` TR-5.9: 推荐岗位与用户需求相关性高，推荐理由合理

## [ ] Task 6: Form Agent Node 实现（包含投递功能 + 记忆功能）
- **Priority**: P0
- **Depends On**: [Task 5]
- **Description**: 
  - 实现 Form Agent Node（LangGraph 节点）
  - 集成通知 Tool（可随时调用通知用户）
  - 实现简历附件上传功能
  - 实现简历解析器选择交互（询问用户是否使用网站自带的简历解析器）
  - 用户选择不使用解析器时的处理：
    - 若网站支持只上传不解析：直接上传，不触发解析流程
    - 若网站上传后自动解析：忽略解析结果，按用户信息重新填写所有字段
  - 用户选择使用解析器时的处理：
    - 使用网站解析器解析简历
    - 自动对比解析内容与用户信息，识别错误和缺失项
    - 自动修正错误内容，补充缺失字段
  - 实现简历表单自动识别
  - 实现智能表单填充（文本框、下拉框、单选按钮、复选框、日历组件等）
  - 处理各种复杂的表单元素
  - **实现信息缺失时的记忆功能（核心新增）**：
    - 遇到必填字段时，调用 `memory.get_field(field_name)` 查询
    - 如果信息缺失：
      1. 通过 LangGraph `interrupt` 暂停执行
      2. 调用通知 Tool 询问用户该字段的值
      3. 用户回答后，调用 `memory.set_field()` 记录到记忆
      4. 自动保存记忆到本地
      5. 恢复执行，使用新值填写表单
    - 如果信息存在（包括之前记忆过的）：直接填入，不再询问
  - 非必填字段信息缺失时，跳过不填
  - 支持不同公司简历系统的自适应
  - **实现投递确认与执行功能**：
    - 完成简历填写后，调用通知 Tool 弹出醒目警告，警告内容：
      > **⚠️ 重要警告**：执行此步，AI agent将直接自动完成简历投递，不会再暂停让您检查并确认，部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，请谨慎选择
    - 询问用户是否由 AI 进行投递（通过通知 Tool 获取用户输入）
    - 若用户选择否，直接结束该公司流程
    - 若用户选择是，执行该公司的投递操作
    - 处理投递过程中的异常
- **Acceptance Criteria Addressed**: [AC-4, AC-5, AC-6, AC-6b, AC-6c, AC-7, AC-8, AC-9, AC-10]
- **Test Requirements**:
  - `programmatic` TR-6.1: Form Agent Node 能成功集成到 StateGraph
  - `programmatic` TR-6.2: 能成功上传简历附件
  - `programmatic` TR-6.3: 能正确询问用户是否使用简历解析器
  - `programmatic` TR-6.4: 用户选择不使用解析器，且网站支持只上传时，能正确只上传不解析
  - `programmatic` TR-6.5: 用户选择不使用解析器，但网站自动解析时，能忽略解析结果重新填写
  - `programmatic` TR-6.6: 用户选择使用解析器时，能正确触发解析流程
  - `programmatic` TR-6.7: 能自动对比解析内容与用户信息，识别并修正错误/补充缺失
  - `programmatic` TR-6.8: 能识别页面上的各种表单元素
  - `programmatic` TR-6.9: 能正确填写文本框、选择下拉菜单、点击单选按钮、勾选复选框
  - `programmatic` TR-6.10: 能正确使用日历组件选择日期
  - `programmatic` TR-6.11: 必填字段信息缺失时，能正确 interrupt 询问用户并记录到记忆
  - `programmatic` TR-6.12: 已记忆的字段再次遇到时，能直接使用不再询问
  - `programmatic` TR-6.13: 非必填字段信息缺失时能正确跳过不填
  - `programmatic` TR-6.14: 能正确调用通知 Tool 弹出指定的醒目警告
  - `programmatic` TR-6.15: 用户选择否时能正确结束该公司流程
  - `programmatic` TR-6.16: 用户选择是时能正确执行投递操作
  - `human-judgement` TR-6.17: 填写内容准确无误，不张冠李戴

## [ ] Task 7: LangGraph 多 Agent 协作与并行处理
- **Priority**: P1
- **Depends On**: [Task 6]
- **Description**: 
  - 使用 LangGraph 实现多个公司流程的并行处理（每个公司一个子图）
  - 实现各节点之间的状态流转：Search Node → Human-in-the-loop → Form Node → Human-in-the-loop → End
  - 实现状态管理（各公司、各节点处理状态跟踪）
  - 支持用户在 Search Agent 推荐岗位后，**自行决定投递的岗位并注册账号，进入简历创建页面**
  - 用户检查期间，Orchestrator 可继续启动其他公司流程
  - 使用 LangGraph 的 `checkpoint` 机制支持断点续传
- **Acceptance Criteria Addressed**: [AC-9]
- **Test Requirements**:
  - `programmatic` TR-7.1: 能并行启动多个公司流程（多个子图同时运行）
  - `programmatic` TR-7.2: 各节点之间能正确状态流转
  - `programmatic` TR-7.3: 能在后台并行处理其他公司
  - `programmatic` TR-7.4: checkpoint 机制能正确保存和恢复状态
  - `human-judgement` TR-7.5: 用户能清晰了解当前处理状态

## [ ] Task 8: 集成测试与文档（含邮箱设置教程 + 记忆功能说明）
- **Priority**: P2
- **Depends On**: [Task 7]
- **Description**: 
  - 端到端集成测试（多 Agent 协作完整流程，包括用户选择 AI 投递和用户选择手动投递两种场景）
  - **记忆功能专项测试**：
    - 模拟缺失必填字段，验证询问-记录-复用流程
    - 验证重启后记忆加载功能
    - 验证记忆查看命令
  - 编写使用文档（包含详细的邮箱设置教程、LangGraph 架构说明、通知 Tool 使用说明、**记忆功能使用说明**）
  - 优化用户体验
- **Acceptance Criteria Addressed**: [AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-6b, AC-6c, AC-7, AC-8, AC-9, AC-10, AC-11, AC-12, AC-13, AC-14, AC-15, AC-16, AC-17, AC-18, AC-19]
- **Test Requirements**:
  - `programmatic` TR-8.1: 端到端多 Agent 协作流程能正常运行（用户选择 AI 投递）
  - `programmatic` TR-8.2: 端到端多 Agent 协作流程能正常运行（用户选择手动投递）
  - `programmatic` TR-8.3: 记忆功能端到端测试：首次遇到缺失字段询问用户，再次遇到直接使用
  - `programmatic` TR-8.4: 记忆持久化测试：重启 Agent 后记忆不丢失
  - `human-judgement` TR-8.5: 文档清晰易懂，包含详细的 LangGraph 架构说明和通知 Tool 使用说明
  - `human-judgement` TR-8.6: 邮箱设置教程详细完整，用户能按步骤配置成功
  - `human-judgement` TR-8.7: 记忆功能说明清晰，用户理解如何查看和管理已记录的信息
