import os
import json
import logging
import smtplib
import requests
from abc import ABC, abstractmethod
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Dict, Any, Optional

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NotificationConfig:
    """通知系统配置类"""
    
    CONFIG_FILE = 'notification_config.json'
    
    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """加载通知配置"""
        if not os.path.exists(cls.CONFIG_FILE):
            # 创建默认配置
            default_config = {
                "enabled": False,
                "methods": {
                    "email": {
                        "enabled": False,
                        "smtp_server": "",
                        "smtp_port": 587,
                        "username": "",
                        "password": "",
                        "sender": "",
                        "recipients": []
                    },
                    "webhook": {
                        "enabled": False,
                        "url": "",
                        "custom_headers": {}
                    },
                    "desktop": {
                        "enabled": False
                    },
                    "telegram": {
                        "enabled": False,
                        "bot_token": "",
                        "chat_id": ""
                    },
                    "wechat": {
                        "enabled": False,
                        "corp_id": "",
                        "corp_secret": "",
                        "agent_id": "",
                        "to_user": "@all"
                    }
                },
                "notification_settings": {
                    "on_new_article": True,
                    "on_feed_error": True,
                    "min_articles_for_notification": 1,
                    "digest_mode": False,
                    "digest_interval": "daily"  # daily, weekly
                }
            }
            
            # 保存默认配置
            with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4, ensure_ascii=False)
            
            return default_config
        
        # 加载现有配置
        try:
            with open(cls.CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"加载通知配置失败: {e}")
            return {"enabled": False}
    
    @classmethod
    def save_config(cls, config: Dict[str, Any]) -> bool:
        """保存通知配置"""
        try:
            with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            logging.error(f"保存通知配置失败: {e}")
            return False
    
    @classmethod
    def update_config(cls, updates: Dict[str, Any]) -> bool:
        """更新部分配置"""
        config = cls.load_config()
        
        # 递归更新字典
        def update_dict(d, u):
            for k, v in u.items():
                if isinstance(v, dict) and k in d and isinstance(d[k], dict):
                    update_dict(d[k], v)
                else:
                    d[k] = v
        
        update_dict(config, updates)
        return cls.save_config(config)


class NotificationEvent:
    """通知事件类，表示一个需要发送通知的事件"""
    
    def __init__(self, event_type: str, title: str, message: str, data: Optional[Dict[str, Any]] = None):
        self.event_type = event_type  # 事件类型: new_article, feed_error, etc.
        self.title = title            # 通知标题
        self.message = message        # 通知内容
        self.data = data or {}        # 附加数据
        self.timestamp = datetime.now()  # 事件发生时间


class NotificationMethod(ABC):
    """通知方法的抽象基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', False)
    
    @abstractmethod
    def send(self, event: NotificationEvent) -> bool:
        """发送通知的抽象方法"""
        pass
    
    def format_message(self, event: NotificationEvent) -> str:
        """格式化通知消息"""
        return f"{event.title}\n\n{event.message}"


class EmailNotification(NotificationMethod):
    """邮件通知"""
    
    def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False
        
        try:
            smtp_server = self.config.get('smtp_server')
            smtp_port = self.config.get('smtp_port', 587)
            username = self.config.get('username')
            password = self.config.get('password')
            sender = self.config.get('sender')
            recipients = self.config.get('recipients', [])
            
            if not smtp_server or not username or not password or not sender or not recipients:
                logging.error("邮件通知配置不完整")
                return False
            
            # 创建邮件
            msg = MIMEMultipart()
            msg['From'] = sender
            msg['To'] = ', '.join(recipients)
            msg['Subject'] = event.title
            
            # 添加HTML内容 - 使用普通字符串拼接而不是f-string
            html_content = """
            <html>
                <head>
                    <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background-color: #f8f9fa; padding: 10px; border-bottom: 1px solid #ddd; }
                        .content { padding: 15px 0; }
                        .footer { font-size: 12px; color: #6c757d; border-top: 1px solid #ddd; padding-top: 10px; }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <div class="header">
                            <h2>""" + event.title + """</h2>
                        </div>
                        <div class="content">
                            """ + event.message.replace('\n', '<br>') + """
                        </div>
                        <div class="footer">
                            此邮件由RSS订阅系统自动发送 - """ + event.timestamp.strftime('%Y-%m-%d %H:%M:%S') + """
                        </div>
                    </div>
                </body>
            </html>
            """
            
            msg.attach(MIMEText(html_content, 'html'))
            
            # 连接SMTP服务器并发送
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
            
            logging.info(f"邮件通知已发送至 {len(recipients)} 个收件人")
            return True
            
        except Exception as e:
            logging.error(f"发送邮件通知失败: {e}")
            return False


class WebhookNotification(NotificationMethod):
    """Webhook通知"""
    
    def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False
        
        try:
            webhook_url = self.config.get('url')
            custom_headers = self.config.get('custom_headers', {})
            
            if not webhook_url:
                logging.error("Webhook URL未配置")
                return False
            
            # 准备发送的数据
            payload = {
                "title": event.title,
                "message": event.message,
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data
            }
            
            # 设置请求头
            headers = {
                "Content-Type": "application/json",
                **custom_headers
            }
            
            # 发送POST请求
            response = requests.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=10
            )
            
            if response.status_code >= 200 and response.status_code < 300:
                logging.info(f"Webhook通知已发送: {response.status_code}")
                return True
            else:
                logging.error(f"Webhook通知发送失败: HTTP {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"发送Webhook通知失败: {e}")
            return False


class DesktopNotification(NotificationMethod):
    """桌面通知"""
    
    def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False
        
        try:
            # 尝试使用平台特定的方法
            import platform
            system = platform.system()
            
            if system == "Darwin":  # macOS
                # 使用osascript发送通知
                os.system(f"""
                osascript -e 'display notification "{event.message}" with title "{event.title}"'
                """)
                logging.info("macOS桌面通知已发送")
                return True
                
            elif system == "Linux":
                # 使用notify-send发送通知
                os.system(f'notify-send "{event.title}" "{event.message}"')
                logging.info("Linux桌面通知已发送")
                return True
                
            elif system == "Windows":
                # 尝试导入win10toast库
                try:
                    # 动态导入，避免启动时错误
                    import importlib
                    win10toast = importlib.import_module('win10toast')
                    toaster = win10toast.ToastNotifier()
                    toaster.show_toast(event.title, event.message, duration=10)
                    logging.info("Windows桌面通知已发送")
                    return True
                except ImportError:
                    logging.error("Windows桌面通知失败: 缺少win10toast库")
                    return False
            
            # 如果以上平台特定方法都不适用，尝试使用plyer
            try:
                # 动态导入，避免启动时错误
                import importlib
                plyer = importlib.import_module('plyer')
                plyer.notification.notify(
                    title=event.title,
                    message=event.message,
                    app_name="RSS订阅系统",
                    timeout=10
                )
                logging.info("Plyer桌面通知已发送")
                return True
            except ImportError:
                logging.error("Plyer桌面通知失败: 缺少plyer库")
                return False
                
            logging.error(f"不支持的操作系统: {system}")
            return False
                
        except Exception as e:
            logging.error(f"发送桌面通知失败: {e}")
            return False


class TelegramNotification(NotificationMethod):
    """Telegram通知"""
    
    def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False
        
        try:
            bot_token = self.config.get('bot_token')
            chat_id = self.config.get('chat_id')
            
            if not bot_token or not chat_id:
                logging.error("Telegram配置不完整")
                return False
            
            # 格式化消息
            message = f"*{event.title}*\n\n{event.message}"
            
            # 发送请求
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logging.info("Telegram通知已发送")
                return True
            else:
                logging.error(f"Telegram通知发送失败: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logging.error(f"发送Telegram通知失败: {e}")
            return False


class WeChatNotification(NotificationMethod):
    """企业微信通知"""
    
    def send(self, event: NotificationEvent) -> bool:
        if not self.enabled:
            return False
        
        try:
            corp_id = self.config.get('corp_id')
            corp_secret = self.config.get('corp_secret')
            agent_id = self.config.get('agent_id')
            to_user = self.config.get('to_user', '@all')
            
            if not corp_id or not corp_secret or not agent_id:
                logging.error("企业微信配置不完整")
                return False
            
            # 获取访问令牌
            token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={corp_secret}"
            token_response = requests.get(token_url, timeout=10)
            token_data = token_response.json()
            
            if token_data.get('errcode') != 0:
                logging.error(f"获取企业微信访问令牌失败: {token_data}")
                return False
                
            access_token = token_data.get('access_token')
            
            # 发送消息
            send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"
            message_data = {
                "touser": to_user,
                "msgtype": "text",
                "agentid": agent_id,
                "text": {
                    "content": f"{event.title}\n\n{event.message}"
                }
            }
            
            send_response = requests.post(send_url, json=message_data, timeout=10)
            send_result = send_response.json()
            
            if send_result.get('errcode') == 0:
                logging.info("企业微信通知已发送")
                return True
            else:
                logging.error(f"企业微信通知发送失败: {send_result}")
                return False
                
        except Exception as e:
            logging.error(f"发送企业微信通知失败: {e}")
            return False


class NotificationManager:
    """通知管理器，负责根据配置发送通知"""
    
    def __init__(self):
        self.config = NotificationConfig.load_config()
        self.enabled = self.config.get('enabled', False)
        self.notification_methods = self._init_notification_methods()
        self.pending_events = []  # 用于存储待发送的通知事件（用于摘要模式）
    
    def _init_notification_methods(self) -> Dict[str, NotificationMethod]:
        """初始化所有通知方法"""
        methods = {}
        
        methods_config = self.config.get('methods', {})
        
        # 初始化各种通知方法
        if 'email' in methods_config:
            methods['email'] = EmailNotification(methods_config['email'])
        
        if 'webhook' in methods_config:
            methods['webhook'] = WebhookNotification(methods_config['webhook'])
        
        if 'desktop' in methods_config:
            methods['desktop'] = DesktopNotification(methods_config['desktop'])
        
        if 'telegram' in methods_config:
            methods['telegram'] = TelegramNotification(methods_config['telegram'])
        
        if 'wechat' in methods_config:
            methods['wechat'] = WeChatNotification(methods_config['wechat'])
        
        return methods
    
    def notify(self, event: NotificationEvent) -> bool:
        """发送通知"""
        if not self.enabled:
            logging.info("通知系统已禁用")
            return False
        
        # 检查通知设置
        settings = self.config.get('notification_settings', {})
        
        # 检查事件类型是否应该通知
        if event.event_type == 'new_article' and not settings.get('on_new_article', True):
            return False
        
        if event.event_type == 'feed_error' and not settings.get('on_feed_error', True):
            return False
        
        # 检查是否使用摘要模式
        if settings.get('digest_mode', False):
            self.pending_events.append(event)
            return True
        
        # 直接发送通知
        return self._send_notification(event)
    
    def _send_notification(self, event: NotificationEvent) -> bool:
        """通过所有启用的通知方法发送通知"""
        success = False
        
        for method_name, method in self.notification_methods.items():
            if method.enabled:
                try:
                    if method.send(event):
                        success = True
                except Exception as e:
                    logging.error(f"{method_name}通知发送失败: {e}")
        
        return success
    
    def send_digest(self) -> bool:
        """发送摘要通知"""
        if not self.pending_events:
            return False
        
        # 按事件类型分组
        events_by_type = {}
        for event in self.pending_events:
            if event.event_type not in events_by_type:
                events_by_type[event.event_type] = []
            events_by_type[event.event_type].append(event)
        
        # 为每种事件类型创建摘要
        for event_type, events in events_by_type.items():
            if event_type == 'new_article':
                title = f"RSS订阅更新摘要: {len(events)}个更新"
                
                # 构建消息内容
                message = "以下RSS源有更新:\n\n"
                
                # 按源分组
                updates_by_feed = {}
                for event in events:
                    feed_title = event.data.get('feed_title', '未知源')
                    if feed_title not in updates_by_feed:
                        updates_by_feed[feed_title] = []
                    updates_by_feed[feed_title].append(event)
                
                # 格式化每个源的更新
                for feed_title, feed_events in updates_by_feed.items():
                    message += f"- {feed_title}: {len(feed_events)}篇新文章\n"
                    for idx, event in enumerate(feed_events[:5]):  # 最多显示5篇
                        message += f"  {idx+1}. {event.data.get('article_title', '未知标题')}\n"
                    if len(feed_events) > 5:
                        message += f"  ... 以及其他{len(feed_events)-5}篇文章\n"
                
                # 创建摘要事件
                digest_event = NotificationEvent(
                    event_type='digest',
                    title=title,
                    message=message,
                    data={'events_count': len(events)}
                )
                
                # 发送摘要通知
                self._send_notification(digest_event)
        
        # 清空待处理事件
        self.pending_events = []
        return True
    
    def update_config(self, new_config: Dict[str, Any]) -> bool:
        """更新通知配置"""
        result = NotificationConfig.update_config(new_config)
        if result:
            # 重新加载配置
            self.config = NotificationConfig.load_config()
            self.enabled = self.config.get('enabled', False)
            self.notification_methods = self._init_notification_methods()
        return result


# 创建全局通知管理器实例
notification_manager = NotificationManager()


def notify_new_articles(feed_title: str, new_articles: List[Dict[str, Any]]) -> bool:
    """通知新文章"""
    if not new_articles:
        return False
    
    # 获取通知设置
    config = NotificationConfig.load_config()
    settings = config.get('notification_settings', {})
    
    # 检查新文章数量是否达到通知阈值
    min_articles = settings.get('min_articles_for_notification', 1)
    if len(new_articles) < min_articles:
        return False
    
    # 构建通知标题和内容
    title = f"RSS更新: {feed_title} 有 {len(new_articles)} 篇新文章"
    
    message = f"订阅源 \"{feed_title}\" 有新的更新:\n\n"
    for idx, article in enumerate(new_articles[:10]):  # 最多显示10篇
        message += f"{idx+1}. {article.get('title', '未知标题')}\n"
    
    if len(new_articles) > 10:
        message += f"\n... 以及其他 {len(new_articles)-10} 篇文章"
    
    # 创建通知事件
    event = NotificationEvent(
        event_type='new_article',
        title=title,
        message=message,
        data={
            'feed_title': feed_title,
            'articles_count': len(new_articles),
            'articles': new_articles
        }
    )
    
    # 发送通知
    return notification_manager.notify(event)


def notify_feed_error(feed_title: str, error_message: str) -> bool:
    """通知RSS源错误"""
    # 构建通知标题和内容
    title = f"RSS源错误: {feed_title}"
    message = f"订阅源 \"{feed_title}\" 更新时发生错误:\n\n{error_message}"
    
    # 创建通知事件
    event = NotificationEvent(
        event_type='feed_error',
        title=title,
        message=message,
        data={
            'feed_title': feed_title,
            'error': error_message
        }
    )
    
    # 发送通知
    return notification_manager.notify(event)


# 如果作为独立脚本运行，进行简单测试
if __name__ == "__main__":
    # 测试通知
    test_event = NotificationEvent(
        event_type='test',
        title='测试通知',
        message='这是一条测试通知消息',
        data={'test': True}
    )
    
    result = notification_manager.notify(test_event)
    print(f"通知发送结果: {'成功' if result else '失败'}")
    
    # 打印当前配置
    print("当前通知配置:")
    print(json.dumps(NotificationConfig.load_config(), indent=2, ensure_ascii=False)) 