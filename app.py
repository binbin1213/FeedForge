from flask import Flask, request, jsonify, g, render_template, send_from_directory, url_for, redirect
import sqlite3
import rss_generator
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote_plus, unquote, urljoin
import xml.etree.ElementTree as ET
import html
from datetime import datetime
from logging_config import setup_logging

app = Flask(__name__)
DATABASE = 'rss_feeds.db'

# 设置日志系统
setup_logging(app)

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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            db.commit()

@app.route('/generate_rss', methods=['POST'])
def generate_rss():
    data = request.get_json()
    url = data['url']
    selector = data.get('selector', '')
    output_file = data['output_file']
    max_pages = data.get('max_pages', 3)  # 默认抓取3页
    
    try:
        result = rss_generator.generate_rss(url, selector, output_file, max_pages)
        
        # 生成RSS订阅链接
        rss_url = url_for('serve_rss', filename=output_file, _external=True)
        
        # 保存到数据库
        db = get_db()
        cursor = db.cursor()
        cursor.execute(
            'INSERT INTO feeds (url, selector, filename) VALUES (?, ?, ?)',
            (url, selector, output_file)
        )
        db.commit()
        
        return jsonify({
            'status': 'success', 
            'file': result['file'],
            'articles_count': result['articles_count'],
            'pages_processed': result['pages_processed'],
            'rss_url': rss_url
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/feeds', methods=['GET'])
def get_feeds():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM feeds ORDER BY created_at DESC')
    feeds = cursor.fetchall()
    return jsonify([{
        'id': row[0],
        'url': row[1],
        'selector': row[2],
        'filename': row[3],
        'created_at': row[4]
    } for row in feeds])

@app.route('/feeds/<int:feed_id>', methods=['POST', 'DELETE'])
def delete_feed(feed_id):
    """删除RSS订阅"""
    try:
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

@app.route('/subscription-list')
def subscription_list():
    """订阅列表页面"""
    try:
        # 获取所有RSS订阅
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM feeds ORDER BY created_at DESC')
        feeds = cursor.fetchall()
        
        # 格式化数据
        feeds_list = []
        for feed in feeds:
            feed_id, source_url, selector, filename, created_at = feed
            rss_url = url_for('serve_rss', filename=filename, _external=True)
            feeds_list.append({
                'id': feed_id,
                'source_url': source_url,
                'selector': selector,
                'filename': filename,
                'created_at': created_at,
                'rss_url': rss_url
            })
        
        return render_template('subscription_list.html', feeds=feeds_list)
    except Exception as e:
        app.logger.error(f"获取订阅列表失败: {e}")
        return render_template('error.html', message=f'获取订阅列表失败: {str(e)}')

@app.route('/')
def index():
    # 获取所有RSS订阅
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM feeds ORDER BY created_at DESC')
    feeds = cursor.fetchall()
    
    # 格式化数据
    feeds_list = []
    for feed in feeds:
        feed_id, source_url, selector, filename, created_at = feed
        rss_url = url_for('serve_rss', filename=filename, _external=True)
        feeds_list.append({
            'id': feed_id,
            'source_url': source_url,
            'selector': selector,
            'filename': filename,
            'created_at': created_at,
            'rss_url': rss_url
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
        file_path = os.path.join(os.getcwd(), filename)
        if not os.path.exists(file_path):
            return jsonify({'error': '文件不存在'}), 404
            
        # 设置正确的Content-Type
        response = send_from_directory(os.getcwd(), filename)
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
            
        feed_id, source_url, selector, filename, created_at = feed
        
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
                                  link=link, 
                                  description=description, 
                                  items=items,
                                  source_url=source_url)
                                  
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

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=8080)