import os
import logging
from logging.handlers import RotatingFileHandler

# 确保日志目录存在
def ensure_log_dir():
    log_dir = os.path.join(os.getcwd(), 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    return log_dir

# 配置日志
def setup_logging(app):
    log_dir = ensure_log_dir()
    log_level = logging.INFO
    
    # 应用日志
    app_log_file = os.path.join(log_dir, 'app.log')
    app_handler = RotatingFileHandler(app_log_file, maxBytes=10485760, backupCount=5)
    app_handler.setLevel(log_level)
    app_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    app.logger.addHandler(app_handler)
    app.logger.setLevel(log_level)
    
    # 访问日志
    access_log_file = os.path.join(log_dir, 'access.log')
    access_handler = RotatingFileHandler(access_log_file, maxBytes=10485760, backupCount=5)
    access_handler.setLevel(log_level)
    access_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(remote_addr)s - "%(request_method)s %(request_path)s" %(status_code)s'
    ))
    
    # 错误日志
    error_log_file = os.path.join(log_dir, 'error.log')
    error_handler = RotatingFileHandler(error_log_file, maxBytes=10485760, backupCount=5)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    app.logger.addHandler(error_handler)
    
    app.logger.info('日志系统已初始化') 