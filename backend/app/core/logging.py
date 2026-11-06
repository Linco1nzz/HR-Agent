"""
日志配置（structlog + 标准库 logging 融合版）

设计目标：
    1. 保留标准库 dictConfig 的 Handler 架构：控制台、普通日志文件（滚动）、错误日志文件（滚动）。
    2. 用 structlog 的 ProcessorFormatter 接管所有 Handler 的格式化：
         - 开发环境：彩色控制台输出（ConsoleRenderer）
         - 生产环境：JSON 输出（JSONRenderer），便于日志采集
    3. 业务代码可用 structlog.get_logger(__name__) 记录结构化字段；
       第三方库（uvicorn、sqlalchemy 等）继续用 logging.getLogger(__name__)，
       其日志会经 foreign_pre_chain 补齐字段后统一渲染。

使用方式：
    1. 项目启动时调用 setup_logging()
    2. 业务代码：
        from app.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("用户登录", user_id=123, action="login")
    3. 标准库风格仍然可用：
        import logging
        logging.getLogger(__name__).info("hello")
"""

from __future__ import annotations

import logging
import logging.config
import os
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.stdlib import ProcessorFormatter

from app.core.config import settings

# ---------------------------------------------------------------------------
# 日志目录：基于项目根目录，避免受进程工作目录影响
# ---------------------------------------------------------------------------
# 本文件位于 app/core/logging.py，项目根 = 上两级目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = _PROJECT_ROOT / "logs"


class SafeStreamHandler(logging.StreamHandler):
    """
    自定义控制台 Handler：
        避免中文/特殊字符在某些终端编码下导致程序报错。
        编码失败时，按 stream 的实际编码做 errors='replace' 兜底。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except UnicodeEncodeError:
            try:
                msg = self.format(record)
                # 用 stream 的实际编码兜底，而不是固定 utf-8
                encoding = getattr(self.stream, "encoding", None) or "utf-8"
                safe_msg = msg.encode(encoding, errors="replace").decode(encoding)
                self.stream.write(safe_msg + self.terminator)
                self.flush()
            except Exception:
                try:
                    self.stream.write("[编码错误] 日志消息无法显示\n")
                    self.flush()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# 自定义 Processor：从标准库的 LogRecord 中提取 module 和 funcName
# ---------------------------------------------------------------------------
def add_module_and_func(logger, method_name, event_dict):
    """
    如果是通过标准库 logging 传入的日志，提取其 record 中的模块和函数名。
    (structlog 原生日志通常不带这些信息，所以做兼容处理)
    """
    record = event_dict.get("_record")
    if record:
        event_dict["module"] = record.module
        event_dict["funcName"] = record.funcName
    return event_dict


# ---------------------------------------------------------------------------
# structlog 共享处理器链
#   既用于 structlog 自身日志，也作为 foreign_pre_chain 处理标准库日志
# ---------------------------------------------------------------------------
def _build_shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
        # 把 exc_info 转成可序列化的 traceback 字符串：
        # 控制台与 JSON 文件都能完整保留堆栈（JSONRenderer 不会自行处理 exc_info）
        structlog.processors.format_exc_info,
        add_module_and_func,  # 自定义处理器：提取 module 和 funcName
    ]


def _build_console_renderer() -> Any:
    """只给控制台用的彩色渲染器"""
    return structlog.dev.ConsoleRenderer(
        colors=True, pad_level=False, exception_formatter=structlog.dev.plain_traceback
    )


def _build_file_renderer() -> Any:
    """专门给日志文件用的渲染器（JSON 或纯文本，绝不能带颜色）"""
    return structlog.processors.JSONRenderer(ensure_ascii=False, indent=2)


def setup_logging() -> None:
    """
    初始化日志系统（幂等，可重复调用）。
    """
    # 1) 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 2) Windows 控制台编码处理：直接重配 stdout/stderr，避免 os.system('chcp') 的副作用
    if os.name == "nt":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
            sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass

    level_name = settings.log_level.upper()

    shared_processors = _build_shared_processors()
    console_renderer = _build_console_renderer()
    file_renderer = _build_file_renderer()

    # 3) 配置 structlog：
    #    - logger_factory 用 stdlib.LoggerFactory，让 structlog 日志最终进入标准库 Handler
    #    - 处理器链末尾用 wrap_for_formatter，交给 ProcessorFormatter 渲染
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # 4) dictConfig：Handler 架构沿用第二版，formatter 统一换成 ProcessorFormatter
    logging_config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "console_structlog": {
                "()": ProcessorFormatter,
                # 给非 structlog 来源的日志（uvicorn/sqlalchemy 等）补齐字段
                "foreign_pre_chain": shared_processors,
                "processors": [
                    ProcessorFormatter.remove_processors_meta,
                    console_renderer,
                ],
            },
            "file_structlog": {
                "()": ProcessorFormatter,
                # 给非 structlog 来源的日志（uvicorn/sqlalchemy 等）补齐字段
                "foreign_pre_chain": shared_processors,
                "processors": [
                    ProcessorFormatter.remove_processors_meta,
                    file_renderer,
                ],
            },
        },
        "handlers": {
            "console": {
                "()": SafeStreamHandler,
                "level": level_name,
                "formatter": "console_structlog",
                "stream": sys.stdout,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": level_name,
                "formatter": "file_structlog",
                "filename": str(LOG_DIR / "hr_agent.log"),
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
            "error_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": "file_structlog",
                "filename": str(LOG_DIR / "hr_agent_error.log"),
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "": {  # 根日志记录器
                "level": level_name,
                "handlers": ["console", "file", "error_file"],
            },
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["console"],
                "propagate": False,
            },
            "sqlalchemy": {
                "level": "WARNING",
                "handlers": ["file"],
                "propagate": False,
            },
        },
    }

    logging.config.dictConfig(logging_config)

    # 5) 初始化完成标记（走 structlog，验证链路可用）
    get_logger(__name__).info("日志配置设置完成", env=settings.app_env)


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------
def get_logger(name: str | None = None) -> Any:
    """获取 structlog logger（支持结构化字段与上下文绑定）。"""
    return structlog.get_logger(name)
