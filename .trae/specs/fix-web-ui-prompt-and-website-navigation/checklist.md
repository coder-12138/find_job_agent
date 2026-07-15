# Checklist

## Web UI 实时对话 - 后端
- [x] SessionInfo 新增 message_history 字段存储对话消息
- [x] SessionInfo 新增 pending_user_messages 字段存储运行中排队消息
- [x] run_company_agent 接收可选 message_history 参数并传入 Agent
- [x] run_company_agent 返回结果中包含完整 messages 列表
- [x] orchestrator 的 run_job_application 透传 message_history
- [x] session_manager 新增 send_message 方法：运行中排队，已完成/出错则重启
- [x] session_manager 新增 interrupt_and_restart 方法：取消当前任务并重启
- [x] _run_agent 在 ainvoke 返回后检查 pending_user_messages 自动续接
- [x] Agent 最终消息通过 push_event 推送 agent_message 事件给前端
- [x] routes.py 新增 POST /api/sessions/{id}/message 端点
- [x] routes.py 新增 POST /api/sessions/{id}/interrupt 端点
- [x] WebSocket 处理新增 user_message 消息类型
- [x] WebSocket 处理新增 interrupt 消息类型

## Web UI 实时对话 - 前端
- [x] 监控页面新增对话历史展示区域
- [x] 对话区域包含输入框与发送按钮
- [x] 对话区域始终可输入（运行中也可发送，消息排队）
- [x] 中断按钮在 Agent 运行中显示
- [x] 中断按钮点击后弹出输入框让用户输入新指令
- [x] 用户消息右对齐，Agent 回复左对齐
- [x] 发送消息后输入框清空
- [x] 支持回车发送消息
- [x] agent_message 事件正确渲染到对话区域

## 官网入口按钮自动点击
- [x] automation.py 新增 click_element_by_text 方法
- [x] click_element_by_text 支持 button/a/[role=button]/input[type=button] 元素
- [x] automation.py 新增 get_visible_buttons 方法
- [x] get_visible_buttons 返回 {text, tag, href, role} 列表
- [x] search.py 新增 click_element_by_text_tool @tool 工具
- [x] search.py 新增 get_visible_buttons_tool @tool 工具
- [x] 两个新工具加入 get_search_tools() 返回列表
- [x] navigate_and_find_positions 导航后自动尝试点击常见入口按钮
- [x] 常见按钮文本覆盖：即刻投递/开始投递/投递简历/查看职位/开始找工作/校招岗位等
- [x] 点击后等待页面加载再提取内容
- [x] 未找到入口按钮时返回信息中列出所有可见按钮

## 用户自行登录/注册引导
- [x] 浏览器默认以非 headless 模式启动
- [x] agent_events.py AgentEventEmitter 新增 request_user_login 抽象方法
- [x] agent_events.py CLIEmitter 实现 request_user_login
- [x] web/emitter.py WebEventEmitter 实现 request_user_login
- [x] WebEventEmitter.request_user_login 推送 user_login 请求事件并 await future
- [x] company_agent.py 新增 request_user_login @tool 工具
- [x] automation.py 新增 check_login_status 方法
- [x] search.py 新增 check_login_status_tool @tool 工具
- [x] 前端 app.js 新增 user_login 请求处理
- [x] 前端登录确认面板展示登录页 URL
- [x] 前端登录确认面板含"已完成登录"按钮
- [x] 前端登录确认面板含"重新检测"按钮
- [x] WebSocket 处理 user_login 响应类型
- [x] check_login_status 检测页面是否含登录/注册按钮
- [x] check_login_status 检测 URL 是否为登录页
- [x] check_login_status 检测是否有用户头像/用户名等登录态标识

## 系统提示与测试
- [x] 系统提示指导 Agent 遇到空页面时调用 get_visible_buttons_tool 与 click_element_by_text_tool
- [x] 系统提示在阶段 3 与阶段 4 之间新增用户登录/注册步骤
- [x] 系统提示包含用户运行中指导消息的说明
- [x] 新增对话续接功能测试
- [x] 新增中断重启测试
- [x] 新增入口按钮工具测试
- [x] 新增登录引导测试
- [x] 全部既有测试无回归
