"""工作流共享上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppContext:
    project_root: Path
    data_root: Path
    json_name: str
    html_name: str
    template_name: str = "需求工作联系单模板.docx"

    @property
    def json_path(self) -> Path:
        return self.data_root / self.json_name

    @property
    def html_path(self) -> Path:
        return self.data_root / self.html_name

    @property
    def template_path(self) -> Path:
        return self.data_root / self.template_name
