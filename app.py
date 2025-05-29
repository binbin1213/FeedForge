from flask import Flask, request, jsonify, g, render_template, send_from_directory, url_for, redirect
import sqlite3
import rss_generator
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus, unquote, urljoin
import xml.etree.ElementTree as ET
import html
from datetime import datetime, timedelta
from logging_config import setup_logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import atexit
import re

app = Flask(__name__)
DATABASE = 'rss_feeds.db'

# 设置日志系统
setup_logging(app)

# 创建调度器
scheduler = BackgroundScheduler()
scheduler.start()

# 注册应用关闭时的清理函数
atexit.register(lambda: scheduler.shutdown())

# 添加上下文处理器，用于导航栏高亮
@app.context_processor
def inject_active_page():
    return {'active_page': request.path}

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    if not os.path.exists(DATABASE):
        with app.app_context():
            db = get_db()
            cursor = db.cursor()
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
            # 设置默认时间戳
            cursor.execute("UPDATE feeds SET created_at = datetime('now') WHERE created_at IS NULL")
            cursor.execute("UPDATE feeds SET updated_at = datetime('now') WHERE updated_at IS NULL")
            db.commit()

def upgrade_db():
    """检查并升级数据库结构"""
    try:
        with app.app_context():
            db = get_db()
            cursor = db.cursor()
            
            # 检查是否需要添加新列
            cursor.execute("PRAGMA table_info(feeds)")
            columns = [column[1] for column in cursor.fetchall()]
            
            # 添加缺失的列
            if 'title' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN title TEXT')
            
            if 'description' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN description TEXT')
                
            if 'article_count' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN article_count INTEGER DEFAULT 0')
                
            if 'last_article_title' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN last_article_title TEXT')
                
            if 'created_at' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN created_at TIMESTAMP')
                # 设置现有记录的created_at为当前时间
                cursor.execute("UPDATE feeds SET created_at = datetime('now') WHERE created_at IS NULL")
                
            # 添加定时更新相关字段
            if 'auto_update' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN auto_update BOOLEAN DEFAULT 0')
                
            if 'update_frequency' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN update_frequency INTEGER DEFAULT 24')
                
            if 'last_check_time' not in columns:
                cursor.execute('ALTER TABLE feeds ADD COLUMN last_check_time TIMESTAMP')
            
            db.commit()
            app.logger.info("数据库结构已检查/升级")
    except Exception as e:
        app.logger.error(f"升级数据库失败: {e}")

@app.route('/generate_rss', methods=['POST'])
def generate_rss():
    data = request.get_json()
    url = data['url']
    selector = data.get('selector', '')
    
    # 先使用域名作为临时文件名
    domain = urlparse(url).netloc
    domain_clean = re.sub(r'[^\w\-]', '_', domain)
    timestamp = datetime.now().strftime('%Y%m%d')
    temp_filename = f"{domain_clean}_{timestamp}.xml"
    
    max_pages = data.get('max_pages', 3)  # 默认抓取3页
    force_update = data.get('force_update', False)  # 是否强制更新
    
    try:
        # 检查数据库中是否已存在相同URL的订阅
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT id, filename, selector FROM feeds WHERE url = ?', (url,))
        existing_feed = cursor.fetchone()
        
        if existing_feed and not force_update:
            # 如果已存在且不强制更新，返回已存在的信息
            feed_id, existing_filename, existing_selector = existing_feed
            rss_url = url_for('serve_rss', filename=existing_filename, _external=True)
            
            # 如果选择器不同，更新选择器
            if selector and selector != existing_selector:
                cursor.execute('UPDATE feeds SET selector = ? WHERE id = ?', (selector, feed_id))
                db.commit()
                app.logger.info(f"更新了已存在订阅的选择器: {url}")
            
            return jsonify({
                'status': 'exists',
                'message': '该URL已存在RSS订阅',
                'feed_id': feed_id,
                'rss_url': rss_url
            })
        
        # 如果不存在或强制更新，则生成新的RSS
        result = rss_generator.generate_rss(url, selector, temp_filename, max_pages)
        
        # 从生成的RSS文件中提取标题中的中文部分作为文件名
        feed_title = extract_feed_title(temp_filename) or ""
        
        # 提取标题中的中文部分
        chinese_title = ""
        if feed_title:
            # 使用正则表达式匹配中文字符
            chinese_match = re.search(r'[\u4e00-\u9fff_]+', feed_title)
            if chinese_match:
                chinese_title = chinese_match.group()
        
        # 如果成功提取到中文标题，使用它作为文件名，否则使用域名
        if chinese_title:
            # 清理标题，去除不适合作为文件名的字符
            clean_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', chinese_title)
            output_file = f"{clean_title}_{timestamp}.xml"
            
            # 确保rss_files目录存在
            rss_dir = os.path.join(os.getcwd(), 'rss_files')
            os.makedirs(rss_dir, exist_ok=True)
            
            # 重命名文件
            old_path = os.path.join(rss_dir, temp_filename)
            new_path = os.path.join(rss_dir, output_file)
            
            if os.path.exists(old_path):
                os.rename(old_path, new_path)
                app.logger.info(f"文件已重命名: {temp_filename} -> {output_file}")
        else:
            output_file = temp_filename
        
        # 生成RSS订阅链接
        rss_url = url_for('serve_rss', filename=output_file, _external=True)
        
        # 使用当前日期时间，格式为YYYY-MM-DD HH:MM:SS
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 获取RSS标题和描述
        feed_description = ""  # 可以从RSS文件中提取，但我们已经将其设为空
        
        # 获取文章数量和最新文章标题
        article_count = result['articles_count']
        last_article_title = ""
        if result.get('articles') and len(result['articles']) > 0:
            last_article_title = result['articles'][0].get('title', '')
        
        if existing_feed and force_update:
            # 如果强制更新已存在的订阅
            feed_id = existing_feed[0]
            cursor.execute(
                '''UPDATE feeds SET 
                   selector = ?, filename = ?, title = ?, description = ?, 
                   article_count = ?, last_article_title = ?, updated_at = ? 
                   WHERE id = ?''',
                (selector, output_file, feed_title, feed_description, 
                 article_count, last_article_title, current_time, feed_id)
            )
            db.commit()
            app.logger.info(f"强制更新了已存在的RSS订阅: {url}")
        else:
            # 创建新订阅
            cursor.execute(
                '''INSERT INTO feeds 
                   (url, selector, filename, title, description, article_count, last_article_title, created_at, updated_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (url, selector, output_file, feed_title, feed_description, 
                 article_count, last_article_title, current_time, current_time)
            )
            db.commit()
            app.logger.info(f"创建了新的RSS订阅: {url}")
        
        return jsonify({
            'status': 'success', 
            'file': result['file'],
            'articles_count': result['articles_count'],
            'pages_processed': result['pages_processed'],
            'rss_url': rss_url
        })
    except Exception as e:
        app.logger.error(f"生成RSS失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/feeds', methods=['GET'])
def get_feeds():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM feeds ORDER BY updated_at DESC')
    feeds = cursor.fetchall()
    return jsonify([{
        'id': row[0],
        'url': row[1],
        'selector': row[2],
        'filename': row[3],
        'updated_at': row[4]
    } for row in feeds])

@app.route('/feeds/<int:feed_id>', methods=['POST', 'DELETE'])
def delete_feed(feed_id):
    """删除RSS订阅"""
    try:
        # 检查是否是表单中的_method=DELETE
        if request.method == 'POST' and request.form.get('_method') == 'DELETE':
            # 继续处理删除操作
            pass
        elif request.method != 'DELETE':
            # 如果不是DELETE方法也不是模拟的DELETE，则返回错误
            return jsonify({'error': '不支持的请求方法'}), 405
            
        db = get_db()
        cursor = db.cursor()
        
        # 获取文件名
        cursor.execute('SELECT filename FROM feeds WHERE id = ?', (feed_id,))
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'error': '未找到对应的RSS订阅'}), 404
            
        filename = result[0]
        
        # 删除数据库记录
        cursor.execute('DELETE FROM feeds WHERE id = ?', (feed_id,))
        db.commit()
        
        # 尝试删除文件
        try:
            file_path = os.path.join(os.getcwd(), filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            app.logger.warning(f"删除文件失败: {e}")
            # 即使删除文件失败，也继续返回成功
        
        # 重定向回首页
        return redirect(url_for('index'))
    except Exception as e:
        app.logger.error(f"删除RSS订阅失败: {e}")
        return jsonify({'error': str(e)}), 500

def extract_domain_name(url):
    """从URL中提取域名"""
    try:
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        # 移除www.前缀
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain
    except:
        return url

def extract_feed_title(filename):
    """从RSS文件中提取频道标题"""
    try:
        import xml.etree.ElementTree as ET
        
        # 先检查完整路径
        file_path = os.path.join(os.getcwd(), filename)
        
        # 如果不存在，则检查rss_files目录
        if not os.path.exists(file_path):
            rss_dir = os.path.join(os.getcwd(), 'rss_files')
            file_path = os.path.join(rss_dir, filename)
            
            # 如果仍然不存在，检查rss_output目录
            if not os.path.exists(file_path):
                rss_output_dir = os.path.join(os.getcwd(), 'rss_output')
                file_path = os.path.join(rss_output_dir, filename)
                
                if not os.path.exists(file_path):
                    app.logger.warning(f"找不到RSS文件: {filename}")
                    return None
            
        # 解析XML文件
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # 获取频道信息
        channel = root.find('channel')
        if not channel:
            return None
            
        title_elem = channel.find('title')
        if title_elem is not None and title_elem.text:
            return title_elem.text
        
        return None
    except Exception as e:
        app.logger.warning(f"提取RSS标题失败: {e}")
        return None

@app.route('/subscription-list')
def subscription_list():
    """订阅列表页面"""
    try:
        # 获取所有RSS订阅
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM feeds ORDER BY updated_at DESC')
        feeds = cursor.fetchall()
        
        # 格式化数据
        feeds_list = []
        for feed in feeds:
            # 只提取需要的字段，忽略其他字段
            feed_id = feed[0]
            source_url = feed[1]
            selector = feed[2]
            filename = feed[3]
            title = feed[4] if len(feed) > 4 else None
            description = feed[5] if len(feed) > 5 else None
            article_count = feed[6] if len(feed) > 6 else 0
            last_article_title = feed[7] if len(feed) > 7 else None
            created_at = feed[8] if len(feed) > 8 else None
            updated_at = feed[9] if len(feed) > 9 else None
            auto_update = feed[10] if len(feed) > 10 else 0
            update_frequency = feed[11] if len(feed) > 11 else 24
            last_check_time = feed[12] if len(feed) > 12 else None
            
            # 格式化日期时间显示
            try:
                if updated_at and len(updated_at) > 19:  # 可能包含毫秒或时区信息
                    updated_at = updated_at[:19]  # 只保留YYYY-MM-DD HH:MM:SS部分
            except:
                pass  # 如果格式化失败，保持原样
            
            # 从文件名中提取ID部分
            short_id = ''
            try:
                if 'rss_' in filename and '.xml' in filename:
                    id_part = filename.split('rss_')[1].split('.xml')[0]
                    short_id = id_part[-6:]  # 取最后6位数字
            except:
                short_id = filename  # 如果提取失败，使用完整文件名
            
            # 从RSS文件中获取频道标题
            feed_title = extract_feed_title(filename)
            
            # 如果无法获取标题，回退到从URL提取域名
            site_name = feed_title or extract_domain_name(source_url)
                
            rss_url = url_for('serve_rss', filename=filename, _external=True)
            
            # 计算下次更新时间
            next_update_time = None
            if auto_update and last_check_time:
                try:
                    last_check = datetime.strptime(last_check_time, '%Y-%m-%d %H:%M:%S')
                    next_update = last_check + timedelta(hours=update_frequency)
                    next_update_time = next_update.strftime('%Y-%m-%d %H:%M:%S')
                except Exception as e:
                    app.logger.error(f"计算下次更新时间失败: {e}")
            
            feeds_list.append({
                'id': feed_id,
                'source_url': source_url,
                'selector': selector,
                'filename': filename,
                'updated_at': updated_at,
                'rss_url': rss_url,
                'short_id': short_id,
                'site_name': site_name,
                'auto_update': bool(auto_update),
                'update_frequency': update_frequency,
                'last_check_time': last_check_time,
                'next_update_time': next_update_time
            })
        
        return render_template('subscription_list.html', feeds=feeds_list)
    except Exception as e:
        app.logger.error(f"获取订阅列表失败: {e}")
        return render_template('error.html', message=f'获取订阅列表失败: {str(e)}')

@app.route('/packages')
def packages():
    """项目结构页面"""
    return render_template('packages.html')

@app.route('/')
def index():
    # 获取所有RSS订阅
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM feeds ORDER BY updated_at DESC')
    feeds = cursor.fetchall()
    
    # 格式化数据
    feeds_list = []
    for feed in feeds:
        # 只提取需要的字段，忽略其他字段
        feed_id = feed[0]
        source_url = feed[1]
        selector = feed[2]
        filename = feed[3]
        title = feed[4] if len(feed) > 4 else None
        description = feed[5] if len(feed) > 5 else None
        article_count = feed[6] if len(feed) > 6 else 0
        last_article_title = feed[7] if len(feed) > 7 else None
        created_at = feed[8] if len(feed) > 8 else None
        updated_at = feed[9] if len(feed) > 9 else None
        auto_update = feed[10] if len(feed) > 10 else 0
        update_frequency = feed[11] if len(feed) > 11 else 24
        last_check_time = feed[12] if len(feed) > 12 else None
        
        # 格式化日期时间显示
        try:
            if updated_at and len(updated_at) > 19:  # 可能包含毫秒或时区信息
                updated_at = updated_at[:19]  # 只保留YYYY-MM-DD HH:MM:SS部分
        except:
            pass  # 如果格式化失败，保持原样
        
        # 从文件名中提取ID部分
        short_id = ''
        try:
            if 'rss_' in filename and '.xml' in filename:
                id_part = filename.split('rss_')[1].split('.xml')[0]
                short_id = id_part[-6:]  # 取最后6位数字
        except:
            short_id = filename  # 如果提取失败，使用完整文件名
        
        # 从RSS文件中获取频道标题
        feed_title = extract_feed_title(filename)
        
        # 如果无法获取标题，回退到从URL提取域名
        site_name = feed_title or extract_domain_name(source_url)
            
        rss_url = url_for('serve_rss', filename=filename, _external=True)
        
        # 计算下次更新时间
        next_update_time = None
        if auto_update and last_check_time:
            try:
                last_check = datetime.strptime(last_check_time, '%Y-%m-%d %H:%M:%S')
                next_update = last_check + timedelta(hours=update_frequency)
                next_update_time = next_update.strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                app.logger.error(f"计算下次更新时间失败: {e}")
        
        feeds_list.append({
            'id': feed_id,
            'source_url': source_url,
            'selector': selector,
            'filename': filename,
            'updated_at': updated_at,
            'rss_url': rss_url,
            'short_id': short_id,
            'site_name': site_name,
            'auto_update': bool(auto_update),
            'update_frequency': update_frequency,
            'last_check_time': last_check_time,
            'next_update_time': next_update_time
        })
    
    return render_template('index.html', feeds=feeds_list)

@app.route('/selector_helper')
def selector_helper():
    """提供选择器助手页面"""
    return app.send_static_file('selector_helper.html')

@app.route('/proxy')
def proxy():
    """代理服务，获取目标网站内容"""
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL参数不能为空'}), 400
    
    try:
        # 添加用户代理以避免被某些网站阻止
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # 获取响应内容类型
        content_type = response.headers.get('Content-Type', '')
        
        # 只处理HTML内容
        if 'text/html' not in content_type and 'application/xhtml+xml' not in content_type:
            return jsonify({'error': '不支持的内容类型，仅支持HTML页面'}), 400
        
        # 获取页面编码
        charset = 'utf-8'  # 默认编码
        if 'charset=' in content_type:
            charset = content_type.split('charset=')[1].split(';')[0].strip()
        
        # 解码内容
        try:
            html = response.content.decode(charset)
        except:
            html = response.text  # 回退到默认处理
        
        # 修改所有链接为绝对路径，防止相对路径链接导致页面跳转
        soup = BeautifulSoup(html, 'html.parser')
        
        # 处理所有链接
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if href.startswith('/'):
                # 相对路径转为绝对路径
                parsed_url = urlparse(url)
                base = f"{parsed_url.scheme}://{parsed_url.netloc}"
                a_tag['href'] = base + href
                # 添加data属性保存原始链接
                a_tag['data-original-href'] = href
            elif not href.startswith(('http://', 'https://', 'javascript:', '#')):
                # 其他相对路径
                if url.endswith('/'):
                    a_tag['href'] = url + href
                else:
                    a_tag['href'] = url + '/' + href
                a_tag['data-original-href'] = href
            # 设置点击事件代理而不是修改href
            a_tag['onclick'] = 'return false;'
            a_tag['class'] = a_tag.get('class', []) + ['proxy-link']
            a_tag['style'] = 'cursor: pointer;'
        
        # 处理所有图片链接
        for img_tag in soup.find_all('img', src=True):
            src = img_tag['src']
            if src.startswith('/'):
                # 相对路径转为绝对路径
                parsed_url = urlparse(url)
                base = f"{parsed_url.scheme}://{parsed_url.netloc}"
                img_tag['src'] = base + src
            elif not src.startswith(('http://', 'https://', 'data:')):
                # 其他相对路径
                if url.endswith('/'):
                    img_tag['src'] = url + src
                else:
                    img_tag['src'] = url + '/' + src
        
        # 禁用所有script标签
        for script in soup.find_all('script'):
            script.decompose()
            
        # 禁用所有iframe标签
        for iframe in soup.find_all('iframe'):
            iframe.decompose()
            
        # 禁用所有form标签
        for form in soup.find_all('form'):
            form.attrs = {}  # 移除所有属性，特别是action
            
        # 将结果包装在一个我们控制的HTML结构中
        result_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>预览: {url}</title>
            <style>
                body {{ margin: 0; padding: 0; font-family: sans-serif; }}
                * {{ box-sizing: border-box; }}
                .highlight {{
                    background-color: rgba(255, 255, 0, 0.3) !important;
                    outline: 2px solid red !important;
                    cursor: pointer !important;
                    position: relative;
                    z-index: 1000;
                }}
                .active-highlight {{
                    background-color: rgba(255, 165, 0, 0.5) !important;
                    outline: 3px solid #ff4500 !important;
                    box-shadow: 0 0 10px rgba(255, 69, 0, 0.7) !important;
                    transition: all 0.2s ease !important;
                    z-index: 9999 !important;
                    position: relative !important;
                    cursor: pointer !important;
                }}
                #proxy-content {{
                    width: 100%;
                    height: 100%;
                    overflow: auto;
                }}
                #debug-overlay {{
                    position: fixed;
                    bottom: 10px;
                    right: 10px;
                    background: rgba(0,0,0,0.7);
                    color: white;
                    padding: 5px;
                    border-radius: 5px;
                    font-size: 12px;
                    z-index: 10000;
                    display: none;
                }}
            </style>
        </head>
        <body>
            <div id="proxy-content">
                {str(soup.body.contents) if soup.body else str(soup)}
            </div>
            <div id="debug-overlay"></div>
            <script>
                // 调试函数
                function debugLog(msg) {{
                    console.log(msg);
                    const overlay = document.getElementById('debug-overlay');
                    overlay.textContent = msg;
                    overlay.style.display = 'block';
                    setTimeout(() => overlay.style.display = 'none', 3000);
                }}
                
                // 初始化
                document.addEventListener('DOMContentLoaded', function() {{
                    debugLog('页面已加载，点击任意元素选择');
                    
                    // 修复内容显示
                    const content = document.getElementById('proxy-content');
                    if (content.innerHTML.indexOf('[') === 0) {{
                        // 修复数组字符串渲染问题
                        try {{
                            const htmlString = content.innerHTML
                                .replace(/\\[|\\]/g, '')
                                .replace(/,/g, '');
                            content.innerHTML = htmlString;
                            debugLog('内容已修复');
                        }} catch(e) {{
                            debugLog('内容修复失败: ' + e.message);
                        }}
                    }}
                    
                    // 为所有元素添加点击事件
                    document.body.addEventListener('click', function(e) {{
                        e.preventDefault();
                        e.stopPropagation();
                        
                        handleElementClick(e.target);
                        return false;
                    }}, true);
                    
                    // 鼠标悬停效果
                    document.body.addEventListener('mouseover', function(e) {{
                        if (!e.target.classList.contains('active-highlight')) {{
                            // 清除其他高亮
                            document.querySelectorAll('.highlight').forEach(el => 
                                el.classList.remove('highlight'));
                            
                            // 高亮当前元素
                            e.target.classList.add('highlight');
                        }}
                    }}, true);
                    
                    document.body.addEventListener('mouseout', function(e) {{
                        if (e.target.classList.contains('highlight')) {{
                            e.target.classList.remove('highlight');
                        }}
                    }}, true);
                }});
                
                // 处理元素点击
                function handleElementClick(element) {{
                    debugLog('元素被点击: ' + element.tagName);
                    
                    // 移除所有高亮
                    document.querySelectorAll('.highlight, .active-highlight').forEach(el => {{
                        el.classList.remove('highlight');
                        el.classList.remove('active-highlight');
                    }});
                    
                    // 添加选中高亮
                    element.classList.add('active-highlight');
                    
                    // 获取元素信息
                    const elementData = getElementData(element);
                    
                    // 发送消息到父窗口
                    try {{
                        window.parent.postMessage({{
                            type: 'elementSelected',
                            element: elementData
                        }}, '*');
                        debugLog('已发送选择消息');
                    }} catch(e) {{
                        debugLog('发送消息失败: ' + e.message);
                    }}
                }}
                
                // 获取元素数据
                function getElementData(element) {{
                    // 基本信息
                    const tagName = element.tagName.toLowerCase();
                    const id = element.id || '';
                    
                    // 类名列表 (过滤掉我们添加的高亮类)
                    let classes = [];
                    if (element.className && typeof element.className === 'string') {{
                        classes = element.className.split(' ')
                            .filter(c => c && !['highlight', 'active-highlight', 'proxy-link'].includes(c));
                    }}
                    
                    // 获取文本内容
                    const text = element.textContent.trim().substring(0, 100);
                    
                    // 生成元素路径
                    let path = '';
                    if (id) {{
                        path = `#${{id}}`;
                    }} else if (classes.length > 0) {{
                        path = `${{tagName}}.${{classes[0]}}`;
                    }} else {{
                        path = tagName;
                        
                        // 添加父元素上下文
                        let parent = element.parentElement;
                        let depth = 0;
                        while (parent && depth < 2) {{
                            const parentTag = parent.tagName.toLowerCase();
                            if (parent.id) {{
                                path = `#${{parent.id}} > ${{path}}`;
                                break;
                            }} else if (parent.className && typeof parent.className === 'string') {{
                                const parentClasses = parent.className.split(' ')
                                    .filter(c => c && !['highlight', 'active-highlight'].includes(c));
                                if (parentClasses.length > 0) {{
                                    path = `${{parentTag}}.${{parentClasses[0]}} > ${{path}}`;
                                    break;
                                }}
                            }}
                            path = `${{parentTag}} > ${{path}}`;
                            parent = parent.parentElement;
                            depth++;
                        }}
                    }}
                    
                    return {{
                        tagName,
                        id,
                        classes,
                        path,
                        text
                    }};
                }}
            </script>
        </body>
        </html>
        """
        
        # 设置响应头，允许iframe加载
        response = app.response_class(
            response=result_html,
            status=200,
            mimetype='text/html'
        )
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'self'"
        
        return response
    except Exception as e:
        app.logger.error(f"代理错误: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/test_selector', methods=['POST'])
def test_selector():
    """测试CSS选择器，返回找到的元素数量和示例"""
    data = request.get_json()
    url = data.get('url')
    selector = data.get('selector')
    
    if not url or not selector:
        return jsonify({'error': 'URL和选择器参数不能为空'}), 400
    
    try:
        # 使用test_selector.py中的功能或直接实现
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        elements = soup.select(selector)
        
        # 准备返回结果
        results = {
            'count': len(elements),
            'elements': []
        }
        
        # 获取前5个元素的文本作为示例
        for i, elem in enumerate(elements[:5]):
            # 尝试找到标题
            title = elem.find(['h1', 'h2', 'h3', 'h4'])
            if title:
                results['elements'].append(title.text.strip())
            else:
                # 如果没有标题标签，显示前50个字符
                text = elem.get_text().strip()
                results['elements'].append(text[:50] + '...')
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/rss/<path:filename>')
def serve_rss(filename):
    """提供RSS文件的访问"""
    try:
        # 检查rss_files目录中是否存在该文件
        rss_dir = os.path.join(os.getcwd(), 'rss_files')
        file_path = os.path.join(rss_dir, filename)
        
        # 如果在新目录找不到，尝试在根目录查找（兼容旧文件）
        if not os.path.exists(file_path):
            old_path = os.path.join(os.getcwd(), filename)
            if os.path.exists(old_path):
                # 设置正确的Content-Type
                response = send_from_directory(os.getcwd(), filename)
                response.headers['Content-Type'] = 'application/xml; charset=utf-8'
                return response
            else:
                return jsonify({'error': '文件不存在'}), 404
            
        # 设置正确的Content-Type
        response = send_from_directory(rss_dir, filename)
        response.headers['Content-Type'] = 'application/xml; charset=utf-8'
        return response
    except Exception as e:
        app.logger.error(f"提供RSS文件访问失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/read/<int:feed_id>')
def read_feed(feed_id):
    """阅读订阅内容"""
    try:
        # 获取RSS订阅信息
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM feeds WHERE id = ?', (feed_id,))
        feed = cursor.fetchone()
        
        if not feed:
            return render_template('error.html', message='未找到该RSS订阅')
            
        # 只提取需要的字段，忽略其他字段
        feed_id = feed[0]
        source_url = feed[1]
        selector = feed[2]
        filename = feed[3]
        auto_update = feed[10] if len(feed) > 10 else 0
        
        # 从文件名中提取ID部分
        short_id = ''
        try:
            if 'rss_' in filename and '.xml' in filename:
                id_part = filename.split('rss_')[1].split('.xml')[0]
                short_id = id_part[-6:]  # 取最后6位数字
        except:
            short_id = filename  # 如果提取失败，使用完整文件名
        
        # 从RSS文件中获取频道标题
        feed_title = extract_feed_title(filename)
        
        # 如果无法获取标题，回退到从URL提取域名
        site_name = feed_title or extract_domain_name(source_url)
        
        # 解析RSS文件
        file_path = os.path.join(os.getcwd(), filename)
        if not os.path.exists(file_path):
            return render_template('error.html', message='RSS文件不存在')
        
        try:
            # 解析XML文件
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            # 获取频道信息
            channel = root.find('channel')
            if not channel:
                return render_template('error.html', message='RSS格式错误')
                
            title_elem = channel.find('title')
            title = title_elem.text if title_elem is not None else '未知标题'
            
            link_elem = channel.find('link')
            link = link_elem.text if link_elem is not None else '#'
            
            description_elem = channel.find('description')
            description = description_elem.text if description_elem is not None else ''
            
            # 获取所有文章
            items = []
            for item in channel.findall('item'):
                item_title = item.find('title')
                item_link = item.find('link')
                item_desc = item.find('description')
                item_date = item.find('pubDate')
                
                # 创建文章对象
                article = {
                    'title': item_title.text if item_title is not None else '无标题',
                    'link': item_link.text if item_link is not None else '#',
                    'description': item_desc.text if item_desc is not None else '',
                    'date': item_date.text if item_date is not None else '',
                    'encoded_link': quote_plus(item_link.text) if item_link is not None and item_link.text else ''
                }
                
                items.append(article)
            
            return render_template('read.html', 
                                  feed_id=feed_id,
                                  title=title, 
                                  short_id=short_id,
                                  site_name=site_name,
                                  link=link, 
                                  description=description, 
                                  items=items,
                                  source_url=source_url,
                                  auto_update=bool(auto_update),
                                  selector=selector)
                                  
        except Exception as e:
            app.logger.error(f"解析RSS文件失败: {e}")
            return render_template('error.html', message=f'解析RSS文件失败: {str(e)}')
    
    except Exception as e:
        app.logger.error(f"读取RSS失败: {e}")
        return render_template('error.html', message=f'读取失败: {str(e)}')

@app.route('/article')
def read_article():
    """阅读单篇文章"""
    try:
        # 获取文章URL
        article_url = request.args.get('url')
        if not article_url:
            return render_template('error.html', message='缺少文章链接参数')
            
        # 解码URL
        article_url = unquote(article_url)
        
        # 获取文章内容
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
        
        response = requests.get(article_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # 解析HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 提取标题和内容
        title = soup.title.string if soup.title else '未知标题'
        
        # 移除不需要的元素
        for tag in soup.find_all(['script', 'style', 'iframe', 'nav', 'footer', 'aside']):
            tag.decompose()
        
        # 提取主要内容
        main_content = None
        
        # 尝试通过常见内容容器选择器查找主要内容
        content_selectors = [
            'article', 'main', '.content', '.article', '.post', 
            '.entry-content', '.post-content', '.article-content', 
            '#content', '.main-content'
        ]
        
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content and len(content.get_text(strip=True)) > 100:
                main_content = content
                break
        
        # 如果找不到内容，使用body作为最后的后备选项
        if not main_content:
            main_content = soup.body
        
        # 确保所有链接是绝对URL
        base_url = article_url
        if main_content:
            for a_tag in main_content.find_all('a', href=True):
                a_tag['href'] = urljoin(base_url, a_tag['href'])
                a_tag['target'] = '_blank'  # 在新标签页打开链接
            
            # 确保所有图片使用绝对URL
            for img_tag in main_content.find_all('img', src=True):
                img_tag['src'] = urljoin(base_url, img_tag['src'])
                # 添加懒加载
                img_tag['loading'] = 'lazy'
        
        # 将内容转为字符串
        content_html = str(main_content)
        
        return render_template('article.html', 
                              title=title, 
                              content=content_html,
                              source_url=article_url)
    
    except Exception as e:
        app.logger.error(f"获取文章失败: {e}")
        return render_template('error.html', message=f'获取文章失败: {str(e)}')

@app.route('/update_feed/<int:feed_id>', methods=['POST'])
def update_feed(feed_id):
    """更新RSS订阅内容"""
    try:
        # 获取RSS订阅信息
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM feeds WHERE id = ?', (feed_id,))
        feed = cursor.fetchone()
        
        if not feed:
            return jsonify({'error': '未找到该RSS订阅'}), 404
            
        # 只提取需要的字段
        feed_id = feed[0]
        source_url = feed[1]
        selector = feed[2]
        old_filename = feed[3]
        
        # 生成临时文件名
        domain = urlparse(source_url).netloc
        domain_clean = re.sub(r'[^\w\-]', '_', domain)
        timestamp = datetime.now().strftime('%Y%m%d')
        temp_filename = f"{domain_clean}_{timestamp}.xml"
        
        # 重新生成RSS，使用增量更新模式
        try:
            max_pages = request.args.get('max_pages', 3, type=int)
            force_full = request.args.get('force_full', False, type=bool)  # 是否强制全量更新
            
            # 调用RSS生成器，传入增量更新参数
            result = rss_generator.generate_rss(
                source_url, 
                selector, 
                temp_filename,  # 使用临时文件名
                max_pages, 
                incremental=not force_full  # 默认使用增量更新
            )
            
            # 从生成的RSS文件中提取标题中的中文部分作为文件名
            feed_title = extract_feed_title(temp_filename) or ""
            
            # 提取标题中的中文部分
            chinese_title = ""
            if feed_title:
                # 使用正则表达式匹配中文字符
                chinese_match = re.search(r'[\u4e00-\u9fff_]+', feed_title)
                if chinese_match:
                    chinese_title = chinese_match.group()
            
            # 如果成功提取到中文标题，使用它作为文件名，否则使用域名
            if chinese_title:
                # 清理标题，去除不适合作为文件名的字符
                clean_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', chinese_title)
                new_filename = f"{clean_title}_{timestamp}.xml"
                
                # 确保rss_files目录存在
                rss_dir = os.path.join(os.getcwd(), 'rss_files')
                os.makedirs(rss_dir, exist_ok=True)
                
                # 重命名文件
                old_path = os.path.join(rss_dir, temp_filename)
                new_path = os.path.join(rss_dir, new_filename)
                
                if os.path.exists(old_path):
                    os.rename(old_path, new_path)
                    app.logger.info(f"文件已重命名: {temp_filename} -> {new_filename}")
            else:
                new_filename = temp_filename
            
            # 更新数据库信息
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 获取文章信息
            article_count = result['articles_count']
            new_articles_count = result.get('new_articles_count', 0)  # 新增的文章数量
            
            # 获取最新文章标题
            last_article_title = ""
            if result.get('articles') and len(result['articles']) > 0:
                last_article_title = result['articles'][0].get('title', '')
            
            # 更新数据库
            cursor.execute('''
                UPDATE feeds 
                SET filename = ?, updated_at = ?, title = ?, article_count = ?, last_article_title = ? 
                WHERE id = ?
            ''', (new_filename, current_time, feed_title, article_count, last_article_title, feed_id))
            db.commit()
            
            # 尝试删除旧文件
            try:
                # 检查旧文件是否在根目录
                old_file_path = os.path.join(os.getcwd(), old_filename)
                if os.path.exists(old_file_path):
                    os.remove(old_file_path)
                
                # 检查旧文件是否在rss_files目录
                old_file_path_in_dir = os.path.join(os.getcwd(), 'rss_files', old_filename)
                if os.path.exists(old_file_path_in_dir):
                    os.remove(old_file_path_in_dir)
            except Exception as e:
                app.logger.warning(f"删除旧文件失败: {e}")
            
            app.logger.info(f"更新RSS成功: ID={feed_id}, URL={source_url}, 共{article_count}篇文章, 新增{new_articles_count}篇")
            
            return jsonify({
                'status': 'success', 
                'message': 'RSS更新成功',
                'articles_count': result['articles_count'],
                'new_articles_count': new_articles_count,
                'pages_processed': result['pages_processed']
            })
        except Exception as e:
            app.logger.error(f"更新RSS失败: {e}")
            return jsonify({'error': f'更新RSS失败: {str(e)}'}), 500
            
    except Exception as e:
        app.logger.error(f"更新RSS订阅失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/set_auto_update/<int:feed_id>', methods=['POST'])
def set_auto_update(feed_id):
    """设置RSS源的自动更新参数"""
    try:
        data = request.get_json()
        auto_update = data.get('auto_update', False)
        update_frequency = data.get('update_frequency', 24)  # 默认24小时
        
        # 验证更新频率
        if update_frequency < 1:
            update_frequency = 1  # 最小1小时
        elif update_frequency > 168:  # 一周
            update_frequency = 168
            
        # 更新数据库
        db = get_db()
        cursor = db.cursor()
        
        # 检查RSS源是否存在
        cursor.execute('SELECT * FROM feeds WHERE id = ?', (feed_id,))
        feed = cursor.fetchone()
        
        if not feed:
            return jsonify({'error': '未找到该RSS订阅'}), 404
            
        # 更新自动更新设置
        cursor.execute(
            'UPDATE feeds SET auto_update = ?, update_frequency = ? WHERE id = ?',
            (1 if auto_update else 0, update_frequency, feed_id)
        )
        db.commit()
        
        # 如果开启了自动更新，更新last_check_time为当前时间
        if auto_update:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                'UPDATE feeds SET last_check_time = ? WHERE id = ?',
                (current_time, feed_id)
            )
            db.commit()
            
        app.logger.info(f"设置RSS自动更新: ID={feed_id}, 自动更新={'开启' if auto_update else '关闭'}, 频率={update_frequency}小时")
        
        return jsonify({
            'status': 'success',
            'message': '自动更新设置已保存',
            'auto_update': auto_update,
            'update_frequency': update_frequency
        })
    except Exception as e:
        app.logger.error(f"设置自动更新失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/get_auto_update/<int:feed_id>', methods=['GET'])
def get_auto_update(feed_id):
    """获取RSS源的自动更新参数"""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            'SELECT auto_update, update_frequency, last_check_time FROM feeds WHERE id = ?', 
            (feed_id,)
        )
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'error': '未找到该RSS订阅'}), 404
            
        auto_update, update_frequency, last_check_time = result
        
        # 计算下次更新时间
        next_update_time = None
        if auto_update and last_check_time:
            try:
                last_check = datetime.strptime(last_check_time, '%Y-%m-%d %H:%M:%S')
                next_update = last_check + timedelta(hours=update_frequency)
                next_update_time = next_update.strftime('%Y-%m-%d %H:%M:%S')
            except Exception as e:
                app.logger.error(f"计算下次更新时间失败: {e}")
        
        return jsonify({
            'auto_update': bool(auto_update),
            'update_frequency': update_frequency,
            'last_check_time': last_check_time,
            'next_update_time': next_update_time
        })
    except Exception as e:
        app.logger.error(f"获取自动更新设置失败: {e}")
        return jsonify({'error': str(e)}), 500

def check_feeds_for_updates():
    """检查需要更新的RSS源并执行更新"""
    app.logger.info("开始检查需要自动更新的RSS源")
    with app.app_context():
        try:
            db = get_db()
            cursor = db.cursor()
            
            # 获取所有启用了自动更新的订阅
            cursor.execute(
                '''SELECT id, url, selector, filename, update_frequency, last_check_time 
                   FROM feeds WHERE auto_update = 1'''
            )
            feeds = cursor.fetchall()
            
            current_time = datetime.now()
            updated_count = 0
            
            for feed in feeds:
                feed_id, url, selector, filename, update_frequency, last_check_time = feed
                
                # 如果没有上次检查时间，或者已经到了更新时间
                should_update = False
                if not last_check_time:
                    should_update = True
                else:
                    # 将字符串时间转换为datetime对象
                    try:
                        last_check = datetime.strptime(last_check_time, '%Y-%m-%d %H:%M:%S')
                        # 计算下次更新时间
                        next_update = last_check + timedelta(hours=update_frequency)
                        if current_time >= next_update:
                            should_update = True
                    except Exception as e:
                        app.logger.error(f"解析时间失败: {e}")
                        should_update = True
                
                if should_update:
                    app.logger.info(f"自动更新RSS源: ID={feed_id}, URL={url}")
                    try:
                        # 生成临时文件名
                        domain = urlparse(url).netloc
                        domain_clean = re.sub(r'[^\w\-]', '_', domain)
                        timestamp = current_time.strftime('%Y%m%d')
                        temp_filename = f"{domain_clean}_{timestamp}.xml"
                        
                        # 调用RSS生成器进行增量更新
                        result = rss_generator.generate_rss(
                            url, 
                            selector, 
                            temp_filename, 
                            max_pages=3,  # 默认抓取3页
                            incremental=True  # 使用增量更新
                        )
                        
                        # 从生成的RSS文件中提取标题中的中文部分作为文件名
                        feed_title = extract_feed_title(temp_filename) or ""
                        
                        # 提取标题中的中文部分
                        chinese_title = ""
                        if feed_title:
                            # 使用正则表达式匹配中文字符
                            chinese_match = re.search(r'[\u4e00-\u9fff_]+', feed_title)
                            if chinese_match:
                                chinese_title = chinese_match.group()
                        
                        # 如果成功提取到中文标题，使用它作为文件名，否则使用域名
                        if chinese_title:
                            # 清理标题，去除不适合作为文件名的字符
                            clean_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', chinese_title)
                            new_filename = f"{clean_title}_{timestamp}.xml"
                            
                            # 确保rss_files目录存在
                            rss_dir = os.path.join(os.getcwd(), 'rss_files')
                            os.makedirs(rss_dir, exist_ok=True)
                            
                            # 重命名文件
                            old_path = os.path.join(rss_dir, temp_filename)
                            new_path = os.path.join(rss_dir, new_filename)
                            
                            if os.path.exists(old_path):
                                os.rename(old_path, new_path)
                                app.logger.info(f"文件已重命名: {temp_filename} -> {new_filename}")
                        else:
                            new_filename = temp_filename
                        
                        # 更新数据库信息
                        current_time_str = current_time.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # 获取文章信息
                        article_count = result['articles_count']
                        new_articles_count = result.get('new_articles_count', 0)
                        
                        # 获取最新文章标题
                        last_article_title = ""
                        if result.get('articles') and len(result['articles']) > 0:
                            last_article_title = result['articles'][0].get('title', '')
                        
                        # 尝试删除旧文件
                        try:
                            # 检查旧文件是否在根目录
                            old_file_path = os.path.join(os.getcwd(), filename)
                            if os.path.exists(old_file_path):
                                os.remove(old_file_path)
                            
                            # 检查旧文件是否在rss_files目录
                            old_file_path_in_dir = os.path.join(os.getcwd(), 'rss_files', filename)
                            if os.path.exists(old_file_path_in_dir):
                                os.remove(old_file_path_in_dir)
                        except Exception as e:
                            app.logger.warning(f"删除旧文件失败: {e}")
                        
                        # 更新数据库
                        cursor.execute(
                            '''UPDATE feeds 
                               SET updated_at = ?, last_check_time = ?, title = ?, 
                                   article_count = ?, last_article_title = ?, filename = ? 
                               WHERE id = ?''',
                            (current_time_str, current_time_str, feed_title, 
                             article_count, last_article_title, new_filename, feed_id)
                        )
                        db.commit()
                        
                        updated_count += 1
                        app.logger.info(f"自动更新成功: ID={feed_id}, 新增{new_articles_count}篇文章")
                    except Exception as e:
                        app.logger.error(f"自动更新RSS源失败: ID={feed_id}, 错误: {e}")
            
            app.logger.info(f"自动更新检查完成，共更新了{updated_count}个RSS源")
        except Exception as e:
            app.logger.error(f"执行自动更新检查时出错: {e}")

# 每小时检查一次需要更新的RSS源
scheduler.add_job(
    func=check_feeds_for_updates,
    trigger=IntervalTrigger(minutes=60),
    id='check_feeds_job',
    name='每小时检查RSS源更新',
    replace_existing=True
)

if __name__ == '__main__':
    # 初始化和升级数据库
    init_db()
    upgrade_db()  # 检查并升级现有数据库结构
    
    # 集成通知系统
    try:
        from notification_integration import integrate_notifications
        integrate_notifications(app)
    except ImportError:
        app.logger.warning("通知系统未找到，通知功能将被禁用")
    
    app.run(debug=True, host='0.0.0.0', port=8081)