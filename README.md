# 校招简历自动投递 Agent

基于 OpenAI Agent SDK + Playwright 的自动校招简历投递工具，支持多公司并行处理、多 Agent 协作、简历解析器集成。

## 功能特性

- **多 Agent 架构**：Orchestrator（协调主 Agent）+ Search Agent（搜索官网）+ Form Agent（填写表单）
- **智能岗位推荐**：根据用户简历和岗位 JD 匹配度，自动推荐最合适的岗位
- **自动表单填写**：支持文本框、下拉菜单、单选按钮、复选框、日历组件等多种表单元素
- **简历解析器集成**：支持使用/不使用网站自带简历解析器两种模式
- **投递确认机制**：表单填写完成后弹出醒目警告，用户确认后才执行投递
- **多平台通知**：终端通知（全平台）+ 系统弹窗（Windows/macOS）+ 邮件通知（可选）
- **并行处理**：支持同时处理多家公司的投递任务
- **Human-in-the-loop**：遇到任何问题 Agent 会暂停并询问用户

## 环境要求

- Python 3.12+
- Conda（推荐）或 pip
- OpenAI API Key（支持 OpenAI API 兼容的第三方服务）

## 快速开始

### 1. 创建 Conda 环境

```bash
conda create -n job_agent python=3.12 -y
conda activate job_agent
```

### 2. 安装依赖

```bash
cd /path/to/find_job_agent
pip install -r requirements.txt

# 安装 Playwright 浏览器（首次使用）
playwright install chromium
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写以下配置：

```env
# OpenAI API 配置（必填）
OPENAI_API_KEY=sk-your-api-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# 邮件通知配置（可选）
EMAIL_NOTIFICATION_ENABLED=false
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_SENDER_EMAIL=your-email@gmail.com
SMTP_SENDER_PASSWORD=your-app-password
SMTP_RECIPIENT_EMAIL=recipient@example.com
```

### 4. 准备个人信息文件

支持 `.json` 和 `.txt/.md` 格式，文件路径默认自动查找：
- 个人信息：`data/personal_information.txt`
- 简历 PDF：`resume_personal_info/` 目录下第一个 PDF 文件

也可以在 `.env` 中指定：

```env
PERSONAL_INFO_FILE_PATH=./data/personal_information.txt
RESUME_FILE_PATH=./resume_personal_info/你的简历.pdf
```

### 5. 运行

```bash
PYTHONPATH=src python -m job_application_agent.main
```

## 个人信息文件格式

### TXT 格式示例

```txt
# 基础信息
姓名：朱一鸣
英文名：zhu yi ming
性别：男
邮箱：zhu-yiming@foxmail.com
出生日期：2001-09-21
民族：汉族
电话：18001894228
证件号码类型：身份证
证件号码：310116200109216418
政治面貌：群众
婚姻状况：未婚
户籍：上海
籍贯：浙江省衢州市
现居住城市：上海
邮编：201108
血型：O型
紧急联系人：俞霖
紧急联系人电话：18049884228

# 求职意向
算法工程师
Agent开发工程师

# 教育经历
## 上海科技大学
就读时间：2024-09 至 2027-06
专业：生物医学工程
学历：硕士研究生
GPA：3.3
排名：前20%
学院：生物医学工程学院

## 山东大学
就读时间：2020-09 至 2024-06
专业：电子信息工程
学历：本科
GPA：82.3

# 实习经历
## 联影医疗
实习时间：2025-04 至 2025-08
部门：中央研究院
岗位：科研合作岗
工作内容：
1. 图形化界面助力人工数据标注
2. 参与论文写作

# 奖惩情况
1. ACM竞赛
   级别：国家级
   奖项：金奖
   获奖时间：2023-05

# 论文和著作
1. Deep Learning for Medical Imaging
   发表会议：ISMRM 2026
   发表时间：2026-05
   发表形式：Traditional Poster
```

### JSON 格式示例

```json
{
  "personal_info": {
    "name": "朱一鸣",
    "gender": "男",
    "email": "zhu-yiming@foxmail.com",
    "phone": "18001894228"
  },
  "education": [
    {
      "school": "上海科技大学",
      "degree": "硕士",
      "major": "生物医学工程",
      "start_date": "2024-09",
      "end_date": "2027-06"
    }
  ],
  "work_experience": [],
  "project_experience": [],
  "awards": [],
  "skills": []
}
```

## 使用流程

### 交互式流程

1. **输入公司信息**：运行时按提示输入公司名称、内推码、岗位关键词、期望城市
2. **岗位搜索**：Agent 自动搜索各公司官网，推荐匹配的岗位
3. **选择岗位**：查看推荐列表，选择要投递的岗位并告知志愿顺序
4. **注册账号**：在目标公司的招聘官网完成账号注册
5. **进入简历页**：注册后进入简历创建页面，告知 Agent 继续
6. **表单填写**：Agent 自动填写简历表单，填写完成后通知你检查
7. **投递确认**：检查无误后，Agent 弹出醒目警告
   - 选择「是」：执行投递
   - 选择「否」：跳过该公司
8. **并行处理**：可以同时处理多家公司，切换窗口操作

### 投递确认警告

当 Agent 执行投递前，会弹出以下警告：

> **⚠️ 重要警告**：执行此步，AI agent 将直接自动完成简历投递，不会再暂停让您检查并确认，部分校招网站一旦投递后，无法（或者很难）修改志愿和投递岗位，请谨慎选择

## 邮件通知配置

### Gmail 邮箱

1. 开启两步验证：https://myaccount.google.com/security
2. 创建应用专用密码：https://myaccount.google.com/apppasswords
3. 在 `.env` 中填入应用专用密码（不是登录密码）

### 其他邮箱

- QQ 邮箱：设置 → 账户 → POP3/SMTP服务 → 生成授权码
- 163 邮箱：设置 → POP3/SMTP/SMTP服务 → 客户端授权密码

## 项目结构

```
job_application_agent/
├── src/job_application_agent/
│   ├── main.py              # 入口文件
│   ├── config.py            # 配置管理
│   ├── context.py           # 全局上下文
│   ├── utils.py             # 工具函数
│   ├── agents/
│   │   ├── orchestrator.py  # 协调主 Agent
│   │   ├── search.py        # Search Agent（搜索官网）
│   │   └── form.py          # Form Agent（表单填写+投递）
│   ├── tools/
│   │   └── notify.py        # 通知 Tool
│   ├── browser/
│   │   └── automation.py    # Playwright 浏览器自动化
│   └── user_info/
│       └── parser.py        # 个人信息解析器
├── data/
│   └── personal_information.txt  # 个人信息文件示例
├── resume_personal_info/
│   └── *.pdf                    # 简历 PDF 文件
├── tests/
│   └── test_basic.py        # 单元测试
├── .env.example             # 环境变量模板
└── requirements.txt         # 依赖列表
```

## 测试

```bash
# 运行所有测试
PYTHONPATH=src python -m pytest tests/ -v

# 运行特定测试
PYTHONPATH=src python -m pytest tests/test_basic.py::TestUserInfo -v
```

## 常见问题

### Q: Linux 服务器无法弹出系统通知？
A: 正常现象。Linux SSH 环境没有桌面，无法弹窗。Agent 会自动降级为终端通知。

### Q: Windows/macOS 弹窗不生效？
A: 1) 确认 `plyer` 库已安装；2) Windows 需以管理员权限运行；3) macOS 需在系统设置中允许通知。

### Q: 表单填写不准确？
A: 1) 检查个人信息文件是否完整；2) 部分网站表单结构特殊，Agent 遇到问题会暂停询问你。

### Q: 如何修改推荐的岗位数量？
A: Agent 会自动从目标公司官网获取最大可投递数 n，然后推荐 2n 个岗位。如果官网未说明，默认推荐 6 个。

### Q: 可以同时处理多少家公司？
A: 默认顺序处理。如果需要并行处理，运行时会询问是否启用并行模式（同时开启多个浏览器窗口）。

## 技术栈

- **OpenAI Agent SDK** (`openai-agents`)：多 Agent 协作框架
- **Playwright**：浏览器自动化
- **Pydantic**：数据验证
- **python-dotenv**：环境变量管理
- **plyer**：跨平台通知

## 注意事项

- 投递前请仔细核对简历信息
- 部分校招网站投递后无法修改，请谨慎确认
- 建议先在测试账号上试用
- 妥善保管 API Key，不要泄露给他人
