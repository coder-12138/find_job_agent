# 自动校招简历投递Agent - Verification Checklist

## 环境与配置验证
- [ ] Checkpoint 1: 成功创建conda环境
- [ ] Checkpoint 2: 成功安装所有依赖（`openai-agents>0.14.1`, Playwright, python-dotenv, plyer等）
- [ ] Checkpoint 3: .env模板文件包含所有必要配置项（API key、url、邮件配置等）
- [ ] Checkpoint 4: 用户信息管理模块能正确读取和存储用户信息，并标记缺失信息

## 多 Agent 架构与 Tool 验证
- [ ] Checkpoint 5: Orchestrator Agent 能成功初始化
- [ ] Checkpoint 6: Search Agent 模板能成功实例化
- [ ] Checkpoint 7: Form Agent 模板能成功实例化
- [ ] Checkpoint 8: Orchestrator 能正确使用 handoffs 和 agent-as-tool 机制
- [ ] Checkpoint 9: 通知 Tool 能正常工作
- [ ] Checkpoint 10: 沙箱功能正确限制文件访问权限（只读用户目录、只写临时目录）

## 浏览器自动化验证
- [ ] Checkpoint 11: 能成功启动浏览器并导航到指定URL
- [ ] Checkpoint 12: 能正确定位和填写文本框
- [ ] Checkpoint 13: 能正确选择下拉菜单选项
- [ ] Checkpoint 14: 能正确点击单选按钮和勾选复选框
- [ ] Checkpoint 15: 能使用日历组件选择日期（精确到月或日根据网站要求）
- [ ] Checkpoint 16: 能成功上传文件

## 通知 Tool 验证
- [ ] Checkpoint 17: 通知 Tool 能正确处理终端打印（全平台）
- [ ] Checkpoint 18: 通知 Tool 的Windows/macOS系统弹窗通知代码实现正确（使用plyer库，平台检测逻辑正确）
- [ ] Checkpoint 19: 通知 Tool 在无桌面环境的Linux上降级为终端通知，不报错
- [ ] Checkpoint 20: 通知 Tool 能成功发送邮件到指定邮箱（如果配置）
- [ ] Checkpoint 21: 通知 Tool 能通过.env控制邮件通知的开关
- [ ] Checkpoint 22: 通知 Tool 能正确获取用户确认输入

## Search Agent 验证
- [ ] Checkpoint 23: Search Agent 能通过搜索引擎找到目标公司的招聘官网
- [ ] Checkpoint 24: Search Agent 能成功导航到招聘官网
- [ ] Checkpoint 25: 能搜索到符合条件的岗位
- [ ] Checkpoint 26: 能正确返回2n个推荐岗位
- [ ] Checkpoint 27: 每个岗位包含岗位名称、工作地点、完整JD
- [ ] Checkpoint 28: 每个岗位包含推荐理由（基于用户简历和岗位匹配度分析）
- [ ] Checkpoint 29: Search Agent 能正确调用通知 Tool 通知用户
- [ ] Checkpoint 30: 推荐岗位与用户需求相关性高，推荐理由合理

## Form Agent 验证（包含投递功能）
- [ ] Checkpoint 31: 能成功上传简历附件
- [ ] Checkpoint 32: 能正确询问用户是否使用简历解析器
- [ ] Checkpoint 33: 用户选择不使用解析器且网站支持只上传时，能正确只上传不解析
- [ ] Checkpoint 34: 用户选择不使用解析器但网站自动解析时，能忽略解析结果重新填写
- [ ] Checkpoint 35: 用户选择使用解析器时，能正确触发解析流程
- [ ] Checkpoint 36: 能自动对比解析内容与用户信息，识别并修正错误/补充缺失
- [ ] Checkpoint 37: 能识别页面上的各种表单元素
- [ ] Checkpoint 38: 能正确填写文本框、选择下拉菜单、点击单选按钮、勾选复选框
- [ ] Checkpoint 39: 信息缺失时能正确跳过不填，不张冠李戴
- [ ] Checkpoint 40: Form Agent 能正确调用通知 Tool 弹出指定的醒目警告
- [ ] Checkpoint 41: 警告内容正确："执行此步，AI agent将直接自动完成简历投递，不会再暂停让您检查并确认，部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，请谨慎选择"
- [ ] Checkpoint 42: 用户选择否时能正确结束该公司流程
- [ ] Checkpoint 43: 用户选择是时能正确执行投递操作

## 多 Agent 协作验证
- [ ] Checkpoint 44: Orchestrator 能并行启动多个公司流程
- [ ] Checkpoint 45: 各 Agent 之间能正确 handoff（Search → Form → 结束）
- [ ] Checkpoint 46: 支持用户在 Search Agent 推荐岗位后，自行决定投递的岗位并注册账号进入简历创建页面
- [ ] Checkpoint 47: 能在后台并行处理其他公司
- [ ] Checkpoint 48: 用户能清晰了解当前处理状态

## 问题处理机制验证
- [ ] Checkpoint 49: Agent遇到未知问题时能正确暂停并调用通知 Tool 询问用户解决方案
- [ ] Checkpoint 50: 用户提供解决方案后能继续执行

## 文档与用户体验验证
- [ ] Checkpoint 51: 端到端多Agent协作流程能正常运行（用户选择AI投递）
- [ ] Checkpoint 52: 端到端多Agent协作流程能正常运行（用户选择手动投递）
- [ ] Checkpoint 53: 文档清晰易懂，包含详细的多Agent架构说明和通知 Tool 使用说明
- [ ] Checkpoint 54: 邮箱设置教程详细完整，用户能按步骤配置成功
