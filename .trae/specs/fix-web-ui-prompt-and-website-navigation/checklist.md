# Checklist

## Web UI 对话续接 - 后端
- [ ] SessionInfo 新增 message_history 字段存储对话消息
- [ ] run_company_agent 接收可选 message_history 参数并传入 Agent
- [ ] run_company_agent 返回结果中包含完整 messages 列表
- [ ] orchestrator 的 run_job_application 透传 message_history 与 emitter
- [ ] session_manager 新增 continue_session 方法：追加用户消息并重启 Agent 任务
- [ ] continue_session 在 Agent 运行中时拒绝（返回错误提示）
- [ ] routes.py 新增 POST /api/sessions/{id}/message 端点
- [ ] WebSocket 处理新增 user_message 消息类型（与 REST 端点等价）
- [ ] Agent 回复通过 push_event 推送 agent_message 事件给前端

## Web UI 对话续接 - 前端
- [ ] 监控页面新增对话历史展示区域
- [ ] 对话区域包含输入框与发送按钮
- [ ] session 运行中（running）时输入框禁用
- [ ] session completed/error 时输入框启用
- [ ] 用户消息与 Agent 回复在对话区域正确渲染
- [ ] 发送消息后输入框清空

## 官网入口按钮自动点击
- [ ] automation.py 新增 click_button_by_text 方法
- [ ] click_button_by_text 支持 button/a/[role=button] 等元素
- [ ] search.py 新增 click_entry_button @tool 工具
- [ ] click_entry_button 加入 get_search_tools() 返回列表
- [ ] navigate_and_find_positions 导航后自动尝试点击常见入口按钮
- [ ] 常见按钮文本覆盖：即刻投递/开始投递/投递简历/查看职位/开始找工作/校招岗位等
- [ ] 点击后等待页面加载再提取内容
- [ ] 返回信息说明是否点击了入口按钮

## 系统提示与测试
- [ ] 系统提示指导 Agent 遇到空页面时主动调用 click_entry_button
- [ ] 新增对话续接功能测试
- [ ] 新增入口按钮点击工具测试
- [ ] 全部既有测试无回归
