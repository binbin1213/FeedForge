# FeedForge (飞阅)

FeedForge (飞阅) 是一个轻量级Web应用，帮助用户为任何网站创建RSS订阅源，即使该网站本身不提供RSS功能。通过直观的界面和智能选择器，轻松将您喜爱的网站内容转换为标准RSS格式，方便在各类RSS阅读器中订阅。

![FeedForge (飞阅)截图](screenshot.png)

## 主要功能

- 🔍 **可视化选择器**：通过交互式界面，点击选择您想要订阅的内容元素
- 📱 **响应式设计**：适配桌面和移动设备的友好界面
- 🔄 **分页支持**：自动识别和处理网站分页，获取更多内容
- 📖 **内置阅读器**：直接在应用内阅读文章，支持夜间模式
- 🔔 **订阅管理**：集中管理所有创建的RSS订阅源

## 安装指南

### 前提条件

- Python 3.7+
- pip (Python包管理器)

### 安装步骤

1. 克隆仓库到本地：

```bash
git clone https://github.com/your-username/feedforge.git
cd feedforge
```

2. 创建并激活虚拟环境（推荐）：

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

3. 安装依赖：

```bash
pip install -r requirements.txt
```

4. 启动应用：

```bash
python app.py
```

5. 在浏览器中访问 http://localhost:8080 开始使用

### Docker部署

如果您偏好使用Docker，我们也提供了容器化部署方案：

1. 确保安装了Docker和Docker Compose

2. 使用Docker Compose启动应用：

```bash
docker-compose up -d
```

3. 在浏览器中访问 http://localhost:8080

4. 停止应用：

```bash
docker-compose down
```

## 使用方法

### 创建新的RSS订阅

1. 点击首页的"创建新RSS"按钮或导航栏中的"创建RSS"
2. 在选择器助手页面，输入想要订阅的网站URL并加载
3. 点击"开始选择"，然后在预览中点击代表文章的元素
4. 系统会自动生成CSS选择器，点击"测试选择器"验证效果
5. 填写输出文件名，点击"生成RSS"完成创建

### 管理订阅

- 在首页或"阅读订阅"页面查看所有创建的RSS订阅
- 使用复制按钮获取RSS链接，添加到您喜欢的RSS阅读器
- 点击"阅读"按钮直接在应用内浏览文章内容
- 使用删除按钮移除不需要的订阅

## 负责任使用说明

本工具设计用于个人使用，请负责任地使用并注意以下事项：

- **尊重网站规则**：请遵守目标网站的robots.txt规则和使用条款
- **合理访问频率**：避免频繁请求同一网站，建议设置合理的更新间隔
- **版权考虑**：RSS内容应仅用于个人阅读，请尊重原创作者的版权
- **个人使用**：本工具设计用于个人订阅需求，不适合大规模数据采集

## 技术实现

- **后端**：Flask (Python Web框架)
- **前端**：HTML, CSS, JavaScript, Bootstrap 5
- **数据解析**：BeautifulSoup4, feedgen
- **数据存储**：SQLite

## 贡献指南

欢迎贡献代码、报告问题或提出新功能建议！

1. Fork项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建Pull Request

## 未来计划

- [ ] 添加robots.txt检查机制
- [ ] 支持更多RSS格式和选项
- [ ] 增加用户账户系统
- [ ] 添加自动更新和推送通知
- [ ] 提供Docker部署支持

## 开源许可

本项目采用 MIT 许可证 - 详情请查看 [LICENSE](LICENSE) 文件

## 免责声明

本工具仅供学习和个人使用。开发者不对使用者通过本工具进行的任何行为负责。使用者应自行承担使用本工具的一切法律责任，并应当遵守相关法律法规及网站的使用条款。 