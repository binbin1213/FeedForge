import logging
from datetime import datetime
from typing import List, Dict, Any

# 导入通知系统
try:
    from notification_system import notification_manager, notify_new_articles, notify_feed_error, NotificationEvent
except ImportError:
    # 如果通知系统不可用，创建空函数
    logging.warning("通知系统未找到，通知功能将被禁用")
    
    def notify_new_articles(feed_title, new_articles):
        return False
    
    def notify_feed_error(feed_title, error_message):
        return False
    
    class NotificationManager:
        def notify(self, *args, **kwargs):
            return False
        
        def send_digest(self):
            return False
            
        def update_config(self, new_config):
            return False
    
    notification_manager = NotificationManager()


def integrate_notifications(app):
    """将通知系统集成到Flask应用中"""
    
    # 保存原始的RSS生成和更新函数
    original_generate_rss = app.view_functions.get('generate_rss')
    original_update_feed = app.view_functions.get('update_feed')
    original_check_feeds_for_updates = None
    
    # 查找check_feeds_for_updates函数
    for func_name in dir(app):
        if func_name == 'check_feeds_for_updates':
            original_check_feeds_for_updates = getattr(app, func_name)
            break
    
    # 如果找不到原始函数，记录警告并返回
    if not original_generate_rss or not original_update_feed:
        app.logger.warning("无法找到原始RSS函数，通知集成失败")
        return
    
    # 包装generate_rss函数，添加通知功能
    def wrapped_generate_rss(*args, **kwargs):
        try:
            # 调用原始函数
            result = original_generate_rss(*args, **kwargs)
            
            # 如果成功生成RSS，发送通知
            if isinstance(result, dict) and result.get('status') == 'success':
                feed_title = result.get('feed_title', '新RSS订阅')
                articles_count = result.get('articles_count', 0)
                
                # 创建通知事件
                event = NotificationEvent(
                    event_type='new_subscription',
                    title=f"新RSS订阅: {feed_title}",
                    message=f"成功创建新的RSS订阅 {feed_title}，包含 {articles_count} 篇文章。",
                    data={
                        'feed_title': feed_title,
                        'articles_count': articles_count,
                        'rss_url': result.get('rss_url', '')
                    }
                )
                
                # 发送通知
                notification_manager.notify(event)
            
            return result
        except Exception as e:
            app.logger.error(f"生成RSS时发生错误: {e}")
            # 发送错误通知
            notify_feed_error('新RSS订阅', str(e))
            raise
    
    # 包装update_feed函数，添加通知功能
    def wrapped_update_feed(feed_id, *args, **kwargs):
        try:
            # 获取更新前的订阅信息
            from flask import g
            db = getattr(g, '_database', None)
            if db:
                cursor = db.cursor()
                cursor.execute('SELECT title, article_count FROM feeds WHERE id = ?', (feed_id,))
                feed_info = cursor.fetchone()
                old_title = feed_info[0] if feed_info else '未知订阅'
                old_article_count = feed_info[1] if feed_info else 0
            else:
                old_title = '未知订阅'
                old_article_count = 0
            
            # 调用原始函数
            result = original_update_feed(feed_id, *args, **kwargs)
            
            # 如果成功更新RSS，发送通知
            if isinstance(result, dict) and result.get('status') == 'success':
                # 获取更新后的订阅信息
                if db:
                    cursor = db.cursor()
                    cursor.execute('SELECT title, article_count, last_article_title FROM feeds WHERE id = ?', (feed_id,))
                    feed_info = cursor.fetchone()
                    feed_title = feed_info[0] if feed_info else old_title
                    new_article_count = feed_info[1] if feed_info else 0
                    last_article_title = feed_info[2] if feed_info else ''
                else:
                    feed_title = old_title
                    new_article_count = result.get('articles_count', 0)
                    last_article_title = ''
                
                # 计算新增文章数
                new_articles_count = result.get('new_articles_count', new_article_count - old_article_count)
                
                # 如果有新文章，发送通知
                if new_articles_count > 0:
                    # 构建新文章列表
                    new_articles = []
                    for i in range(min(new_articles_count, 10)):  # 最多10篇
                        if i == 0 and last_article_title:
                            title = last_article_title
                        else:
                            title = f"新文章 #{i+1}"
                        
                        new_articles.append({
                            'title': title,
                            'link': '',  # 没有链接信息
                            'description': ''
                        })
                    
                    # 发送新文章通知
                    notify_new_articles(feed_title, new_articles)
            
            return result
        except Exception as e:
            app.logger.error(f"更新RSS时发生错误: {e}")
            # 发送错误通知
            notify_feed_error(f"RSS订阅 #{feed_id}", str(e))
            raise
    
    # 包装check_feeds_for_updates函数，添加通知功能
    if original_check_feeds_for_updates:
        def wrapped_check_feeds_for_updates():
            try:
                # 调用原始函数
                original_check_feeds_for_updates()
                
                # 发送摘要通知（如果启用）
                notification_manager.send_digest()
                
            except Exception as e:
                app.logger.error(f"自动检查RSS更新时发生错误: {e}")
                # 发送错误通知
                notify_feed_error('RSS自动更新', str(e))
                raise
        
        # 替换原始函数
        setattr(app, 'check_feeds_for_updates', wrapped_check_feeds_for_updates)
    
    # 替换原始函数
    app.view_functions['generate_rss'] = wrapped_generate_rss
    app.view_functions['update_feed'] = wrapped_update_feed
    
    # 添加通知配置页面路由
    @app.route('/notification_settings', methods=['GET', 'POST'])
    def notification_settings():
        """通知设置页面"""
        from flask import request, render_template, jsonify, redirect, url_for, flash
        
        if request.method == 'POST':
            try:
                # 获取表单数据
                data = {}
                
                # 通知触发条件
                data['notification_settings'] = {
                    'on_new_article': 'notify_on_new' in request.form,
                    'on_feed_error': 'notify_on_error' in request.form,
                    'min_articles_for_notification': 1,
                    'digest_mode': False,
                    'digest_interval': 'daily'
                }
                
                # 设置全局启用状态
                data['enabled'] = ('notify_on_new' in request.form or 'notify_on_error' in request.form)
                
                # 邮件通知设置
                data['methods'] = {
                    'email': {
                        'enabled': 'email_enabled' in request.form,
                        'smtp_server': request.form.get('email_smtp_server', ''),
                        'smtp_port': int(request.form.get('email_smtp_port', 587)),
                        'username': request.form.get('email_username', ''),
                        'password': request.form.get('email_password', ''),
                        'from_addr': request.form.get('email_from', ''),
                        'to_addr': request.form.get('email_to', ''),
                        'use_ssl': 'email_use_ssl' in request.form
                    },
                    'webhook': {
                        'enabled': 'webhook_enabled' in request.form,
                        'url': request.form.get('webhook_url', ''),
                        'method': request.form.get('webhook_method', 'POST')
                    },
                    'desktop': {
                        'enabled': 'desktop_enabled' in request.form
                    },
                    'telegram': {
                        'enabled': 'telegram_enabled' in request.form,
                        'bot_token': request.form.get('telegram_bot_token', ''),
                        'chat_id': request.form.get('telegram_chat_id', '')
                    },
                    'wechat': {
                        'enabled': 'wechat_work_enabled' in request.form,
                        'webhook_url': request.form.get('wechat_work_webhook', '')
                    }
                }
                
                # 更新通知配置
                if notification_manager.update_config(data):
                    flash('通知设置已更新', 'success')
                    return redirect(url_for('notification_settings'))
                else:
                    flash('更新通知设置失败', 'danger')
                    return redirect(url_for('notification_settings'))
            except Exception as e:
                app.logger.error(f"更新通知设置失败: {e}")
                flash(f'更新通知设置失败: {str(e)}', 'danger')
                return redirect(url_for('notification_settings'))
        else:
            # 获取当前配置
            try:
                from notification_system import NotificationConfig
                config = NotificationConfig.load_config()
                
                # 转换配置格式以匹配模板中的变量名
                settings = {
                    'notify_on_new': config.get('notification_settings', {}).get('on_new_article', False),
                    'notify_on_error': config.get('notification_settings', {}).get('on_feed_error', False),
                    'email_enabled': config.get('methods', {}).get('email', {}).get('enabled', False),
                    'email_smtp_server': config.get('methods', {}).get('email', {}).get('smtp_server', ''),
                    'email_smtp_port': config.get('methods', {}).get('email', {}).get('smtp_port', 587),
                    'email_username': config.get('methods', {}).get('email', {}).get('username', ''),
                    'email_password': config.get('methods', {}).get('email', {}).get('password', ''),
                    'email_from': config.get('methods', {}).get('email', {}).get('from_addr', ''),
                    'email_to': config.get('methods', {}).get('email', {}).get('to_addr', ''),
                    'email_use_ssl': config.get('methods', {}).get('email', {}).get('use_ssl', False),
                    'webhook_enabled': config.get('methods', {}).get('webhook', {}).get('enabled', False),
                    'webhook_url': config.get('methods', {}).get('webhook', {}).get('url', ''),
                    'webhook_method': config.get('methods', {}).get('webhook', {}).get('method', 'POST'),
                    'desktop_enabled': config.get('methods', {}).get('desktop', {}).get('enabled', False),
                    'telegram_enabled': config.get('methods', {}).get('telegram', {}).get('enabled', False),
                    'telegram_bot_token': config.get('methods', {}).get('telegram', {}).get('bot_token', ''),
                    'telegram_chat_id': config.get('methods', {}).get('telegram', {}).get('chat_id', ''),
                    'wechat_work_enabled': config.get('methods', {}).get('wechat', {}).get('enabled', False),
                    'wechat_work_webhook': config.get('methods', {}).get('wechat', {}).get('webhook_url', '')
                }
                
                return render_template('notification_settings.html', settings=settings)
            except Exception as e:
                app.logger.error(f"加载通知设置失败: {e}")
                return render_template('error.html', message=f'加载通知设置失败: {str(e)}')
    
    # 添加测试通知路由
    @app.route('/test_notification', methods=['POST'])
    def test_notification():
        """测试通知功能"""
        from flask import request, jsonify
        
        try:
            # 获取表单数据
            data = request.get_json()
            method = data.get('method', '')
            
            # 创建测试通知事件
            event = NotificationEvent(
                event_type='test',
                title='测试通知',
                message=f'这是一条测试通知消息，发送时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
                data={'test': True, 'method': method}
            )
            
            # 如果指定了特定通知方法
            if method and method in notification_manager.notification_methods:
                result = notification_manager.notification_methods[method].send(event)
            else:
                # 否则使用所有启用的方法
                result = notification_manager.notify(event)
            
            if result:
                return jsonify({'status': 'success', 'message': '测试通知已发送'})
            else:
                return jsonify({'status': 'error', 'message': '发送测试通知失败，请检查通知设置'}), 500
        except Exception as e:
            app.logger.error(f"发送测试通知失败: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500
    
    app.logger.info("通知系统已集成到应用中")


def create_notification_templates():
    """创建通知系统所需的模板文件"""
    import os
    
    # 通知设置页面模板
    notification_settings_template = """
{% extends "base.html" %}

{% block title %}通知设置{% endblock %}

{% block content %}
<div class="container mt-4">
    <h1 class="mb-4">通知设置</h1>
    
    <div class="card mb-4">
        <div class="card-header">
            <h5 class="mb-0">通知系统</h5>
        </div>
        <div class="card-body">
            <form id="notification-form">
                <div class="form-check form-switch mb-3">
                    <input class="form-check-input" type="checkbox" id="enable-notifications" 
                           {% if config.enabled %}checked{% endif %}>
                    <label class="form-check-label" for="enable-notifications">启用通知</label>
                </div>
                
                <h5 class="mt-4">通知触发条件</h5>
                <div class="form-check mb-2">
                    <input class="form-check-input" type="checkbox" id="notify-new-articles" 
                           {% if config.notification_settings.on_new_article %}checked{% endif %}>
                    <label class="form-check-label" for="notify-new-articles">RSS源有新文章时通知</label>
                </div>
                
                <div class="form-check mb-2">
                    <input class="form-check-input" type="checkbox" id="notify-feed-error" 
                           {% if config.notification_settings.on_feed_error %}checked{% endif %}>
                    <label class="form-check-label" for="notify-feed-error">RSS源更新失败时通知</label>
                </div>
                
                <div class="mb-3">
                    <label for="min-articles" class="form-label">通知的最小文章数量</label>
                    <input type="number" class="form-control" id="min-articles" min="1" max="100"
                           value="{{ config.notification_settings.min_articles_for_notification }}">
                    <div class="form-text">只有当新文章数量达到或超过此值时才会发送通知</div>
                </div>
                
                <div class="form-check mb-2">
                    <input class="form-check-input" type="checkbox" id="digest-mode" 
                           {% if config.notification_settings.digest_mode %}checked{% endif %}>
                    <label class="form-check-label" for="digest-mode">使用摘要模式</label>
                    <div class="form-text">摘要模式会收集一段时间内的通知，然后一次性发送</div>
                </div>
                
                <div class="mb-3" id="digest-interval-container" 
                     {% if not config.notification_settings.digest_mode %}style="display:none"{% endif %}>
                    <label for="digest-interval" class="form-label">摘要发送频率</label>
                    <select class="form-select" id="digest-interval">
                        <option value="daily" {% if config.notification_settings.digest_interval == 'daily' %}selected{% endif %}>
                            每日摘要
                        </option>
                        <option value="weekly" {% if config.notification_settings.digest_interval == 'weekly' %}selected{% endif %}>
                            每周摘要
                        </option>
                    </select>
                </div>
                
                <h5 class="mt-4">通知方式</h5>
                <ul class="nav nav-tabs" id="notification-tabs" role="tablist">
                    <li class="nav-item" role="presentation">
                        <button class="nav-link active" id="email-tab" data-bs-toggle="tab" data-bs-target="#email" 
                                type="button" role="tab" aria-controls="email" aria-selected="true">邮件通知</button>
                    </li>
                    <li class="nav-item" role="presentation">
                        <button class="nav-link" id="webhook-tab" data-bs-toggle="tab" data-bs-target="#webhook" 
                                type="button" role="tab" aria-controls="webhook" aria-selected="false">Webhook</button>
                    </li>
                    <li class="nav-item" role="presentation">
                        <button class="nav-link" id="desktop-tab" data-bs-toggle="tab" data-bs-target="#desktop" 
                                type="button" role="tab" aria-controls="desktop" aria-selected="false">桌面通知</button>
                    </li>
                    <li class="nav-item" role="presentation">
                        <button class="nav-link" id="telegram-tab" data-bs-toggle="tab" data-bs-target="#telegram" 
                                type="button" role="tab" aria-controls="telegram" aria-selected="false">Telegram</button>
                    </li>
                    <li class="nav-item" role="presentation">
                        <button class="nav-link" id="wechat-tab" data-bs-toggle="tab" data-bs-target="#wechat" 
                                type="button" role="tab" aria-controls="wechat" aria-selected="false">企业微信</button>
                    </li>
                </ul>
                
                <div class="tab-content p-3 border border-top-0 rounded-bottom" id="notification-tab-content">
                    <!-- 邮件通知设置 -->
                    <div class="tab-pane fade show active" id="email" role="tabpanel" aria-labelledby="email-tab">
                        <div class="form-check form-switch mb-3">
                            <input class="form-check-input" type="checkbox" id="enable-email" 
                                   {% if config.methods.email.enabled %}checked{% endif %}>
                            <label class="form-check-label" for="enable-email">启用邮件通知</label>
                        </div>
                        
                        <div class="mb-3">
                            <label for="smtp-server" class="form-label">SMTP服务器</label>
                            <input type="text" class="form-control" id="smtp-server" 
                                   value="{{ config.methods.email.smtp_server }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="smtp-port" class="form-label">SMTP端口</label>
                            <input type="number" class="form-control" id="smtp-port" 
                                   value="{{ config.methods.email.smtp_port }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="smtp-username" class="form-label">用户名</label>
                            <input type="text" class="form-control" id="smtp-username" 
                                   value="{{ config.methods.email.username }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="smtp-password" class="form-label">密码</label>
                            <input type="password" class="form-control" id="smtp-password" 
                                   value="{{ config.methods.email.password }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="smtp-sender" class="form-label">发件人</label>
                            <input type="email" class="form-control" id="smtp-sender" 
                                   value="{{ config.methods.email.sender }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="smtp-recipients" class="form-label">收件人</label>
                            <textarea class="form-control" id="smtp-recipients" rows="2">{{ config.methods.email.recipients|join('\n') }}</textarea>
                            <div class="form-text">每行一个邮箱地址</div>
                        </div>
                        
                        <button type="button" class="btn btn-sm btn-primary" onclick="testNotification('email')">
                            测试邮件通知
                        </button>
                    </div>
                    
                    <!-- Webhook设置 -->
                    <div class="tab-pane fade" id="webhook" role="tabpanel" aria-labelledby="webhook-tab">
                        <div class="form-check form-switch mb-3">
                            <input class="form-check-input" type="checkbox" id="enable-webhook" 
                                   {% if config.methods.webhook.enabled %}checked{% endif %}>
                            <label class="form-check-label" for="enable-webhook">启用Webhook通知</label>
                        </div>
                        
                        <div class="mb-3">
                            <label for="webhook-url" class="form-label">Webhook URL</label>
                            <input type="url" class="form-control" id="webhook-url" 
                                   value="{{ config.methods.webhook.url }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="webhook-headers" class="form-label">自定义请求头</label>
                            <textarea class="form-control" id="webhook-headers" rows="3">{% for key, value in config.methods.webhook.custom_headers.items() %}{{ key }}: {{ value }}
{% endfor %}</textarea>
                            <div class="form-text">每行一个请求头，格式为 "名称: 值"</div>
                        </div>
                        
                        <button type="button" class="btn btn-sm btn-primary" onclick="testNotification('webhook')">
                            测试Webhook通知
                        </button>
                    </div>
                    
                    <!-- 桌面通知设置 -->
                    <div class="tab-pane fade" id="desktop" role="tabpanel" aria-labelledby="desktop-tab">
                        <div class="form-check form-switch mb-3">
                            <input class="form-check-input" type="checkbox" id="enable-desktop" 
                                   {% if config.methods.desktop.enabled %}checked{% endif %}>
                            <label class="form-check-label" for="enable-desktop">启用桌面通知</label>
                        </div>
                        
                        <div class="alert alert-info">
                            桌面通知需要系统支持，并且浏览器必须授予通知权限。
                        </div>
                        
                        <button type="button" class="btn btn-sm btn-primary" onclick="testNotification('desktop')">
                            测试桌面通知
                        </button>
                    </div>
                    
                    <!-- Telegram设置 -->
                    <div class="tab-pane fade" id="telegram" role="tabpanel" aria-labelledby="telegram-tab">
                        <div class="form-check form-switch mb-3">
                            <input class="form-check-input" type="checkbox" id="enable-telegram" 
                                   {% if config.methods.telegram.enabled %}checked{% endif %}>
                            <label class="form-check-label" for="enable-telegram">启用Telegram通知</label>
                        </div>
                        
                        <div class="mb-3">
                            <label for="telegram-token" class="form-label">Bot Token</label>
                            <input type="text" class="form-control" id="telegram-token" 
                                   value="{{ config.methods.telegram.bot_token }}">
                            <div class="form-text">从 @BotFather 获取的机器人令牌</div>
                        </div>
                        
                        <div class="mb-3">
                            <label for="telegram-chat-id" class="form-label">Chat ID</label>
                            <input type="text" class="form-control" id="telegram-chat-id" 
                                   value="{{ config.methods.telegram.chat_id }}">
                            <div class="form-text">用户或群组的Chat ID</div>
                        </div>
                        
                        <button type="button" class="btn btn-sm btn-primary" onclick="testNotification('telegram')">
                            测试Telegram通知
                        </button>
                    </div>
                    
                    <!-- 企业微信设置 -->
                    <div class="tab-pane fade" id="wechat" role="tabpanel" aria-labelledby="wechat-tab">
                        <div class="form-check form-switch mb-3">
                            <input class="form-check-input" type="checkbox" id="enable-wechat" 
                                   {% if config.methods.wechat.enabled %}checked{% endif %}>
                            <label class="form-check-label" for="enable-wechat">启用企业微信通知</label>
                        </div>
                        
                        <div class="mb-3">
                            <label for="wechat-corp-id" class="form-label">企业ID</label>
                            <input type="text" class="form-control" id="wechat-corp-id" 
                                   value="{{ config.methods.wechat.corp_id }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="wechat-corp-secret" class="form-label">应用Secret</label>
                            <input type="text" class="form-control" id="wechat-corp-secret" 
                                   value="{{ config.methods.wechat.corp_secret }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="wechat-agent-id" class="form-label">应用AgentId</label>
                            <input type="text" class="form-control" id="wechat-agent-id" 
                                   value="{{ config.methods.wechat.agent_id }}">
                        </div>
                        
                        <div class="mb-3">
                            <label for="wechat-to-user" class="form-label">接收人</label>
                            <input type="text" class="form-control" id="wechat-to-user" 
                                   value="{{ config.methods.wechat.to_user }}">
                            <div class="form-text">接收人的userid，多个接收人用'|'分隔，所有人填写@all</div>
                        </div>
                        
                        <button type="button" class="btn btn-sm btn-primary" onclick="testNotification('wechat')">
                            测试企业微信通知
                        </button>
                    </div>
                </div>
                
                <div class="mt-4">
                    <button type="button" class="btn btn-primary" onclick="saveSettings()">保存设置</button>
                </div>
            </form>
        </div>
    </div>
</div>

<script>
    // 显示/隐藏摘要间隔设置
    document.getElementById('digest-mode').addEventListener('change', function() {
        document.getElementById('digest-interval-container').style.display = this.checked ? 'block' : 'none';
    });
    
    // 保存设置
    function saveSettings() {
        // 收集表单数据
        const config = {
            enabled: document.getElementById('enable-notifications').checked,
            methods: {
                email: {
                    enabled: document.getElementById('enable-email').checked,
                    smtp_server: document.getElementById('smtp-server').value,
                    smtp_port: parseInt(document.getElementById('smtp-port').value),
                    username: document.getElementById('smtp-username').value,
                    password: document.getElementById('smtp-password').value,
                    sender: document.getElementById('smtp-sender').value,
                    recipients: document.getElementById('smtp-recipients').value.split('\\n').filter(s => s.trim())
                },
                webhook: {
                    enabled: document.getElementById('enable-webhook').checked,
                    url: document.getElementById('webhook-url').value,
                    custom_headers: parseHeaders(document.getElementById('webhook-headers').value)
                },
                desktop: {
                    enabled: document.getElementById('enable-desktop').checked
                },
                telegram: {
                    enabled: document.getElementById('enable-telegram').checked,
                    bot_token: document.getElementById('telegram-token').value,
                    chat_id: document.getElementById('telegram-chat-id').value
                },
                wechat: {
                    enabled: document.getElementById('enable-wechat').checked,
                    corp_id: document.getElementById('wechat-corp-id').value,
                    corp_secret: document.getElementById('wechat-corp-secret').value,
                    agent_id: document.getElementById('wechat-agent-id').value,
                    to_user: document.getElementById('wechat-to-user').value
                }
            },
            notification_settings: {
                on_new_article: document.getElementById('notify-new-articles').checked,
                on_feed_error: document.getElementById('notify-feed-error').checked,
                min_articles_for_notification: parseInt(document.getElementById('min-articles').value),
                digest_mode: document.getElementById('digest-mode').checked,
                digest_interval: document.getElementById('digest-interval').value
            }
        };
        
        // 发送到服务器
        fetch('/notification_settings', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(config)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert('通知设置已保存');
            } else {
                alert('保存失败: ' + data.message);
            }
        })
        .catch(error => {
            alert('保存失败: ' + error);
        });
    }
    
    // 解析请求头
    function parseHeaders(headersText) {
        const headers = {};
        const lines = headersText.split('\\n');
        
        for (const line of lines) {
            const parts = line.split(':');
            if (parts.length >= 2) {
                const key = parts[0].trim();
                const value = parts.slice(1).join(':').trim();
                if (key && value) {
                    headers[key] = value;
                }
            }
        }
        
        return headers;
    }
    
    // 测试通知
    function testNotification(method) {
        fetch('/test_notification', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ method })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert('测试通知已发送');
            } else {
                alert('发送测试通知失败: ' + data.message);
            }
        })
        .catch(error => {
            alert('发送测试通知失败: ' + error);
        });
    }
</script>
{% endblock %}
"""
    
    # 检查templates目录是否存在
    templates_dir = os.path.join(os.getcwd(), 'templates')
    if not os.path.exists(templates_dir):
        os.makedirs(templates_dir)
    
    # 创建通知设置页面模板
    with open(os.path.join(templates_dir, 'notification_settings.html'), 'w', encoding='utf-8') as f:
        f.write(notification_settings_template)
    
    print("通知系统模板文件已创建")


# 如果作为独立脚本运行，创建模板文件
if __name__ == "__main__":
    create_notification_templates() 