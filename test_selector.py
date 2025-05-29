import sys
import requests
from bs4 import BeautifulSoup

def test_selector(url, selector):
    """测试CSS选择器并显示找到的元素数量和标题"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        elements = soup.select(selector)
        
        print(f"\n测试选择器: '{selector}'")
        print(f"找到 {len(elements)} 个元素")
        
        if elements:
            print("\n前5个元素的标题或文本:")
            for i, elem in enumerate(elements[:5]):
                # 尝试找到标题
                title = elem.find(['h1', 'h2', 'h3', 'h4'])
                if title:
                    print(f"{i+1}. {title.text.strip()}")
                else:
                    # 如果没有标题标签，显示前50个字符
                    text = elem.get_text().strip()
                    print(f"{i+1}. {text[:50]}...")
        
        return len(elements) > 0
    except Exception as e:
        print(f"错误: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("使用方法: python test_selector.py <网站URL> <CSS选择器>")
        print("例如: python test_selector.py https://example.com .post")
        sys.exit(1)
    
    url = sys.argv[1]
    selector = sys.argv[2]
    
    test_selector(url, selector) 