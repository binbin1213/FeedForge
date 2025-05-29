import sys
import os
import requests
import re
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_page_content(url, headers=None):
    """获取网页内容"""
    if not headers:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logging.error(f"获取页面失败: {url}, 错误: {e}")
        return None

def find_pagination_links(soup, base_url):
    """寻找分页链接"""
    pagination_links = []
    
    # 常见的分页容器选择器
    pagination_selectors = [
        '.pagination', '.pager', '.page-numbers', '.pages', 
        'nav.navigation', 'ul.page-numbers', '.pagenavi',
        '.wp-pagenavi', '.pagelist', '.page-links', '.nav-links'
    ]
    
    # 尝试所有可能的分页选择器
    for selector in pagination_selectors:
        pagination = soup.select_one(selector)
        if pagination:
            # 找到分页容器后，获取所有链接
            for a_tag in pagination.find_all('a', href=True):
                # 排除"下一页"、"上一页"等特殊链接
                skip_texts = ['next', 'prev', '下一页', '上一页', '首页', '尾页']
                if not any(text in a_tag.text.lower() for text in skip_texts):
                    page_url = urljoin(base_url, a_tag['href'])
                    if page_url not in pagination_links:
                        pagination_links.append(page_url)
            break
    
    # 如果没有找到分页，检查是否有数字作为页码的链接
    if not pagination_links:
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            text = a_tag.text.strip()
            # 检查链接是否包含page关键字或链接文本是否为数字
            if ('page' in href or '/page/' in href or text.isdigit()) and len(text) < 5:
                page_url = urljoin(base_url, href)
                if page_url not in pagination_links:
                    pagination_links.append(page_url)
    
    # 排序并去重
    pagination_links = list(set(pagination_links))
    logging.info(f"找到 {len(pagination_links)} 个分页链接")
    return pagination_links

def extract_articles_from_page(soup, selector, base_url):
    """从单个页面中提取文章信息"""
    articles = []
    elements = soup.select(selector)
    
    for element in elements:
        try:
            # 获取标题
            title_element = element.find(['h1', 'h2', 'h3', 'a']) or element
            title = title_element.get_text().strip()
            
            # 获取链接
            link_element = element.find('a') if element.name != 'a' else element
            link = urljoin(base_url, link_element['href']) if link_element and link_element.has_attr('href') else ''
            
            # 获取描述/摘要
            description = ''
            desc_element = element.find(['p', '.excerpt', '.summary', '.description'])
            if desc_element:
                description = desc_element.get_text().strip()
            else:
                # 如果没有找到描述，使用元素本身的文本
                description = element.get_text().strip()
                # 限制描述长度
                if len(description) > 300:
                    description = description[:300] + '...'
            
            # 获取图片（如果有）
            image_url = ''
            img_element = element.find('img')
            if img_element and img_element.has_attr('src'):
                image_url = urljoin(base_url, img_element['src'])
            
            # 添加到文章列表
            articles.append({
                'title': title,
                'link': link,
                'description': description,
                'image_url': image_url
            })
        except Exception as e:
            logging.error(f"处理文章元素时出错: {e}")
    
    return articles

def generate_rss(url, selector, output_file=None, max_pages=3):
    """生成RSS feed"""
    if not url:
        raise ValueError("URL不能为空")
    
    if not selector:
        # 如果没有提供选择器，使用一些常见的文章选择器
        selector = 'article, .post, .entry, .article, .blog-post, .item, .post-item, .post-card, h2.entry-title > a'
    
    # 如果没有提供输出文件，使用域名作为文件名
    if not output_file:
        domain = urlparse(url).netloc
        output_file = f"{domain.replace('.', '_')}.xml"
    
    # 获取网页内容
    html = get_page_content(url)
    if not html:
        raise Exception(f"无法获取页面内容: {url}")
    
    # 解析HTML
    soup = BeautifulSoup(html, 'html.parser')
    
    # 获取网站标题
    site_title = soup.title.string if soup.title else urlparse(url).netloc
    site_description = f"从 {url} 生成的RSS feed"
    
    # 初始化文章列表
    all_articles = []
    
    # 首先从当前页面提取文章
    page_articles = extract_articles_from_page(soup, selector, url)
    all_articles.extend(page_articles)
    logging.info(f"从主页找到 {len(page_articles)} 篇文章")
    
    # 查找分页链接
    pagination_links = find_pagination_links(soup, url)
    
    # 限制爬取页数
    pagination_links = pagination_links[:max_pages-1]  # 减1是因为已经爬取了首页
    
    # 爬取额外页面
    for page_url in pagination_links:
        logging.info(f"正在处理分页: {page_url}")
        page_html = get_page_content(page_url)
        if page_html:
            page_soup = BeautifulSoup(page_html, 'html.parser')
            page_articles = extract_articles_from_page(page_soup, selector, url)
            all_articles.extend(page_articles)
            logging.info(f"从分页 {page_url} 找到 {len(page_articles)} 篇文章")
    
    # 如果没有找到文章，抛出异常
    if not all_articles:
        raise Exception(f"使用选择器 '{selector}' 没有找到任何文章")
    
    # 创建RSS feed
    fg = FeedGenerator()
    fg.title(site_title)
    fg.link(href=url)
    fg.description(site_description)
    fg.language('zh-CN')
    fg.generator('RSS Generator')
    
    # 添加额外的RSS元数据
    fg.lastBuildDate(datetime.now(timezone.utc))
    
    # 添加文章到RSS
    for article in all_articles:
        fe = fg.add_entry()
        fe.title(article['title'])
        fe.link(href=article['link'])
        
        # 构建内容，包括图片
        content = article['description']
        if article['image_url']:
            content = f"<img src='{article['image_url']}' alt='{article['title']}' /><br/>{content}"
        
        # 添加更多字段
        fe.description(content)
        fe.guid(article['link'])  # 使用链接作为唯一标识符
        
        # 使用当前时间（带时区）
        current_time = datetime.now(timezone.utc)
        fe.pubDate(current_time)
    
    # 保存RSS文件
    output_path = os.path.join(os.getcwd(), output_file)
    fg.rss_file(output_path, pretty=True)  # 使用pretty=True使XML格式更易读
    logging.info(f"RSS已生成，共包含 {len(all_articles)} 篇文章，保存到 {output_path}")
    
    return {
        'file': output_path,
        'url': url,
        'articles_count': len(all_articles),
        'pages_processed': len(pagination_links) + 1
    }

if __name__ == "__main__":
    # 解析命令行参数
    if len(sys.argv) < 2:
        print("用法: python rss_generator.py <网站URL> [CSS选择器] [输出文件名] [最大页数]")
        sys.exit(1)
    
    url = sys.argv[1]
    selector = sys.argv[2] if len(sys.argv) > 2 else ""
    output_file = sys.argv[3] if len(sys.argv) > 3 else None
    max_pages = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    
    try:
        result = generate_rss(url, selector, output_file, max_pages)
        print(f"RSS生成成功！")
        print(f"文件: {result['file']}")
        print(f"包含 {result['articles_count']} 篇文章")
        print(f"处理了 {result['pages_processed']} 个页面")
    except Exception as e:
        print(f"生成RSS失败: {e}")
        sys.exit(1)