# 自动校招简历投递Agent - Verification Checklist

## 环境与配置验证
- [ ] Checkpoint 1: 成功创建conda环境
- [ ] Checkpoint 2: 成功安装所有依赖（`langchain`, `langgraph`, Playwright, python-dotenv, plyer等）
- [ ] Checkpoint 3: .env模板文件包含所有必要配置项（API key、url、邮件配置等）
- [ ] Checkpoint 4: 用户信息管理模块能正确读取和存储用户信息，并标记缺失信息

## 记忆存储模块验证
- [ ] Checkpoint 5: `AgentMemory` 数据结构能正确初始化（`source_user_info`, `learned_fields`, `field_metadata`, `company_history`）
- [ ] Checkpoint 6: `get_field(field_name)` 能正确优先从 `learned_fields` 查找，再从 `source_user_info` 查找
- [ ] Checkpoint 7: `set_field(field_name, value, reason)` 能正确记录字段值并附带时间戳和原因到 `field_metadata`
- [ ] Checkpoint 8: 记忆数据能正确持久化到本地文件（JSON 或 SQLite）
- [ ] Checkpoint 9: Agent 重启后能正确加载之前保存的记忆数据
- [ ] Checkpoint 10: 用户能通过命令行查看已记录的所有补充信息
- [ ] Checkpoint 11: 记忆数据仅保存在本地，不上传到任何外部服务

## LangGraph 架构与节点验证
- [ ] Checkpoint 12: LangGraph `StateGraph` 能成功构建和编译
- [ ] Checkpoint 13: Orchestrator Node 能成功初始化并管理全局状态
- [ ] Checkpoint 14: Router Node 能正确根据状态路由到目标节点（Search / Form / Human-in-the-loop / End）
- [ ] Checkpoint 15: Search Agent Node 能成功集成到 StateGraph
- [ ] Checkpoint 16: Form Agent Node 能成功集成到 StateGraph
- [ ] Checkpoint 17: Human-in-the-loop Node 能正确使用 LangGraph `interrupt` 暂停执行并恢复
- [ ] Checkpoint 18: Memory Update Node 能在用户回答后正确调用 `set_field` 并触发持久化
- [ ] Checkpoint 19: LangGraph `checkpoint` 机制能正确保存和恢复执行状态

## 通知 Tool 验证
- [ ] Checkpoint 20: 通知 Tool 能正确处理终端打印（全平台）
- [ ] Checkpoint 21: 通知 Tool 的Windows/macOS系统弹窗通知代码实现正确（使用plyer库，平台检测逻辑正确）
- [ ] Checkpoint 22: 通知 Tool 在无桌面环境的Linux上降级为终端通知，不报错
- [ ] Checkpoint 23: 通知 Tool 能成功发送邮件到指定邮箱（如果配置）
- [ ] Checkpoint 24: 通知 Tool 能通过.env控制邮件通知的开关
- [ ] Checkpoint 25: 通知 Tool 能正确获取用户确认输入

## 浏览器自动化验证
- [ ] Checkpoint 26: 能成功启动浏览器并导航到指定URL
- [ ] Checkpoint 27: 能正确定位和填写文本框
- [ ] Checkpoint 28: 能正确选择下拉菜单选项
- [ ] Checkpoint 29: 能正确点击单选按钮和勾选复选框
- [ ] Checkpoint 30: 能使用日历组件选择日期（精确到月或日根据网站要求）
- [ ] Checkpoint 31: 能成功上传文件

## Search Agent Node 验证
- [ ] Checkpoint 32: Search Agent Node 能通过搜索引擎找到目标公司的招聘官网
- [ ] Checkpoint 33: Search Agent Node 能成功导航到招聘官网
- [ ] Checkpoint 34: 能搜索到符合条件的岗位
- [ ] Checkpoint 35: 能正确返回2n个推荐岗位
- [ ] Checkpoint 36: 每个岗位包含岗位名称、工作地点、完整JD
- [ ] Checkpoint 37: 每个岗位包含推荐理由（基于用户简历和岗位匹配度分析）
- [ ] Checkpoint 38: Search Agent Node 能正确调用通知 Tool 通知用户
- [ ] Checkpoint 39: 推荐岗位与用户需求相关性高，推荐理由合理

## Form Agent Node 验证（包含投递功能 + 记忆功能）
- [ ] Checkpoint 40: 能成功上传简历附件
- [ ] Checkpoint 41: 能正确询问用户是否使用简历解析器
- [ ] Checkpoint 42: 用户选择不使用解析器且网站支持只上传时，能正确只上传不解析
- [ ] Checkpoint 43: 用户选择不使用解析器但网站自动解析时，能忽略解析结果重新填写
- [ ] Checkpoint 44: 用户选择使用解析器时，能正确触发解析流程
- [ ] Checkpoint 45: 能自动对比解析内容与用户信息，识别并修正错误/补充缺失
- [ ] Checkpoint 46: 能识别页面上的各种表单元素
- [ ] Checkpoint 47: 能正确填写文本框、选择下拉菜单、点击单选按钮、勾选复选框
- [ ] Checkpoint 48: **记忆功能 - 必填字段缺失时**：能正确通过 LangGraph `interrupt` 暂停并询问用户
- [ ] Checkpoint 49: **记忆功能 - 记录答案**：用户回答后，能正确调用 `memory.set_field()` 记录并持久化
- [ ] Checkpoint 50: **记忆功能 - 复用记忆**：已记录的字段再次遇到时，能直接使用不再询问
- [ ] Checkpoint 51: 非必填字段信息缺失时能正确跳过不填，不张冠李戴
- [ ] Checkpoint 52: Form Agent Node 能正确调用通知 Tool 弹出指定的醒目警告
- [ ] Checkpoint 53: 警告内容正确："执行此步，AI agent将直接自动完成简历投递，不会再暂停让您检查并确认，部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，请谨慎选择"
- [ ] Checkpoint 54: 用户选择否时能正确结束该公司流程
- [ ] Checkpoint 55: 用户选择是时能正确执行投递操作

## 多 Agent 协作与并行验证
- [ ] Checkpoint 56: Orchestrator 能并行启动多个公司流程（多个 LangGraph 子图）
- [ ] Checkpoint 57: 各节点之间能正确状态流转（Search → Human-in-the-loop → Form → Human-in-the-loop → End）
- [ ] Checkpoint 58: 支持用户在 Search Agent 推荐岗位后，自行决定投递的岗位并注册账号进入简历创建页面
- [ ] Checkpoint 59: 能在后台并行处理其他公司
- [ ] Checkpoint 60: 用户能清晰了解当前处理状态

## 问题处理机制验证
- [ ] Checkpoint 61: Agent遇到未知问题时能正确暂停并调用通知 Tool 询问用户解决方案
- [ ] Checkpoint 62: 用户提供解决方案后能继续执行

## 文档与用户体验验证
- [ ] Checkpoint 63: 端到端多Agent协作流程能正常运行（用户选择AI投递）
- [ ] Checkpoint 64: 端到端多Agent协作流程能正常运行（用户选择手动投递）
- [ ] Checkpoint 65: 文档清晰易懂，包含详细的 LangGraph 架构说明和通知 Tool 使用说明
- [ ] Checkpoint 66: 邮箱设置教程详细完整，用户能按步骤配置成功
- [ ] Checkpoint 67: 记忆功能说明清晰，用户理解如何查看和管理已记录的信息
