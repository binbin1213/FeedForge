FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（不包括数据库和数据文件）
COPY . .

# 创建数据目录
RUN mkdir -p /app/rss_files /app/rss_output

# 确保数据库文件不存在，让应用自动创建
RUN rm -f /app/rss_feeds.db

# 确保启动脚本有执行权限
RUN chmod +x /app/start.sh

# 设置环境变量
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PORT=8080

# 暴露端口
EXPOSE 8080

# 启动应用
CMD ["/app/start.sh"] 