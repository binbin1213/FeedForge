# FeedForge (飞阅)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.7+](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-2.0.1-orange.svg)](https://flask.palletsprojects.com/)
[![Docker](https://img.shields.io/badge/Docker-支持-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
[![Website](https://img.shields.io/badge/网站-飞阅RSS生成器-ff69b4)](https://github.com/binbin1213/FeedForge)
![Repo Size](https://img.shields.io/github/repo-size/binbin1213/FeedForge)
![Release](https://img.shields.io/badge/版本-1.1.0-success)
![Last Commit](https://img.shields.io/github/last-commit/binbin1213/FeedForge)
![RSS](https://img.shields.io/badge/RSS-飞阅订阅-FFA500?logo=rss)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/binbin1213/FeedForge)

FeedForge (飞阅) 是一个轻量级Web应用，帮助您为任何网站创建RSS订阅源，即使该网站本身不提供RSS功能。通过直观的界面和智能选择器，您可以轻松将喜爱的网站内容转换为标准RSS格式，方便在各类RSS阅读器中订阅。支持Docker部署，一键安装即可开始使用。

## 主要功能

- 🔍 **可视化选择器**：通过交互式界面，点击选择您想要订阅的内容元素
- 📱 **响应式设计**：适配桌面和移动设备的友好界面
- 🔄 **分页支持**：自动识别和处理网站分页，获取更多内容
- 📖 **内置阅读器**：直接在应用内阅读文章，支持夜间模式
- 🔔 **订阅管理**：集中管理所有创建的RSS订阅源
- 📊 **增量更新**：智能识别新文章，只更新新内容，减少资源消耗
- ⏱️ **定时更新**：支持自动定时更新，可自定义更新频率
- 📣 **多渠道通知**：支持邮件、Webhook、桌面通知、Telegram和企业微信等多种通知方式
- 🐳 **Docker支持**：提供官方Docker镜像和docker-compose配置，一键部署

## 快速开始

### 方式一：使用Docker（推荐）

```bash
# 创建项目目录
mkdir -p FeedForge/{rss_files,rss_output,logs,docker_data}
cd FeedForge

# 下载docker-compose配置文件
curl -O https://raw.githubusercontent.com/binbin1213/FeedForge/main/docker-compose.hub.yml

# 启动容器
docker-compose -f docker-compose.hub.yml up -d
```

### 方式二：从源码安装

```bash
# 克隆仓库
git clone https://github.com/binbin1213/FeedForge.git
cd FeedForge

# 创建并激活虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 启动应用
python app.py
```

启动完成后，访问 http://localhost:8080 即可开始使用 FeedForge！

## 详细文档

更多详细的使用说明、功能介绍和配置指南，请访问：
- [在线文档](https://binbin1213.github.io/FeedForge/)
- [本地文档](./docs/) - 包含完整的功能说明和配置指南
- [版本更新日志](./RELEASE_NOTES.md) - 查看最新功能和改进

## 技术实现

- **后端**：Flask (Python Web框架)
- **前端**：HTML, CSS, JavaScript, Bootstrap 5
- **数据解析**：BeautifulSoup4, feedgen
- **数据存储**：SQLite
- **通知系统**：支持SMTP、HTTP、桌面通知、Telegram API和企业微信API
- **容器化**：Docker, Docker Compose
- **持续集成**：GitHub Actions

## 未来计划

- [x] 添加定时自动更新功能，支持自定义更新频率
- [ ] 添加robots.txt检查机制
- [x] 支持增量更新机制
- [x] 显示文章更新统计
- [x] 优化订阅源标题显示
- [ ] 支持更多RSS格式和选项
- [x] 添加推送通知功能
- [x] 提供Docker部署支持
- [ ] 支持批量导入/导出订阅
- [ ] 添加更多阅读体验优化选项

## 开源许可

本项目采用 MIT 许可证 - 详情请查看 [LICENSE](./LICENSE) 文件

## 免责声明

本工具仅供学习和个人使用。开发者不对使用者通过本工具进行的任何行为负责。使用者应自行承担使用本工具的一切法律责任，并应当遵守相关法律法规及网站的使用条款。 
