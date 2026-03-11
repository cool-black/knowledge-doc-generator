"""
工作流状态管理
支持断点续传和容错恢复
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum


class WorkflowStep(Enum):
    """工作流步骤"""
    INIT = "init"
    TOPIC_INPUT = "topic_input"
    DOC_TYPE_SELECTED = "doc_type_selected"
    SOURCES_RETRIEVED = "sources_retrieved"
    SOURCES_FILTERED = "sources_filtered"
    OUTLINE_CONFIRMED = "outline_confirmed"
    CONTENT_GENERATING = "content_generating"
    CONTENT_COMPLETED = "content_completed"
    EXPORTED = "exported"


@dataclass
class WorkflowState:
    """工作流状态"""
    # 基本信息
    topic: str = ""
    doc_type: str = ""
    step: str = WorkflowStep.INIT.value
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 检索结果
    sources: List[Dict[str, Any]] = field(default_factory=list)
    filtered_sources: List[Dict[str, Any]] = field(default_factory=list)

    # 大纲
    outline: Optional[Dict[str, Any]] = None

    # 生成进度
    generated_content: str = ""  # 已生成的内容
    completed_sections: List[str] = field(default_factory=list)  # 已完成章节标题
    total_sections: int = 0  # 总章节数
    current_section_index: int = 0  # 当前章节索引

    # 错误信息
    last_error: str = ""
    error_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowState":
        """从字典创建"""
        return cls(**data)


class WorkflowStateManager:
    """工作流状态管理器"""

    STATE_FILE = ".workflow_state.json"

    def __init__(self, state_dir: str = "."):
        self.state_path = os.path.join(state_dir, self.STATE_FILE)

    def save(self, state: WorkflowState):
        """保存状态"""
        state.updated_at = datetime.now().isoformat()
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self) -> Optional[WorkflowState]:
        """加载状态"""
        if not os.path.exists(self.state_path):
            return None
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return WorkflowState.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return None

    def clear(self):
        """清除状态"""
        if os.path.exists(self.state_path):
            os.remove(self.state_path)

    def exists(self) -> bool:
        """检查状态文件是否存在"""
        return os.path.exists(self.state_path)

    def get_state_age_minutes(self) -> Optional[float]:
        """获取状态文件年龄（分钟）"""
        if not self.exists():
            return None
        try:
            mtime = os.path.getmtime(self.state_path)
            age_seconds = datetime.now().timestamp() - mtime
            return age_seconds / 60
        except OSError:
            return None
