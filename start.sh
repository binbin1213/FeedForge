#!/bin/bash

# 启动脚本 - 确保数据库正确初始化

# 执行初始化数据库的Python代码
python -c "
import sqlite3
import os

DATABASE = '/app/rss_feeds.db'

# 创建或连接数据库
conn = sqlite3.connect(DATABASE)
cursor = conn.cursor()

# 检查feeds表是否存在
cursor.execute(\"\"\"
    SELECT name FROM sqlite_master 
    WHERE type='table' AND name='feeds'
\"\"\")

table_exists = cursor.fetchone()

if not table_exists:
    print('创建feeds表...')
    cursor.execute('''
        CREATE TABLE feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            selector TEXT,
            filename TEXT NOT NULL,
            title TEXT,
            description TEXT,
            article_count INTEGER DEFAULT 0,
            last_article_title TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            auto_update BOOLEAN DEFAULT 0,
            update_frequency INTEGER DEFAULT 24,
            last_check_time TIMESTAMP
        )
    ''')
    conn.commit()
    print('数据库表创建完成!')
else:
    print('数据库表已存在，跳过初始化')

conn.close()
"

# 启动Flask应用
echo "启动Flask应用..."
exec python app.py 