"""工作流共享上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re


@dataclass(frozen=True)
class AppContext:
    project_root: Path
    data_root: Path
    json_name: str
    html_name: str
    template_name: str = "需求工作联系单模板.docx"
    local_ai_base_url: str = "http://127.0.0.1:8080/v1"
    local_ai_model: str = "Qwen3.8-27B-Q4_K_M.gguf"
    local_ai_api_key: str = ""
    local_ai_request_timeout_sec: int = 180
    work_contact_root: Path | None = None

    @property
    def json_path(self) -> Path:
        return self.data_root / self.json_name

    @property
    def html_path(self) -> Path:
        return self.data_root / self.html_name

    @property
    def template_path(self) -> Path:
        return self.data_root / self.template_name

    def template_path_for_date(self, document_date: date) -> Path:
        """Return the latest dated template effective on the document date."""
        dated_templates: list[tuple[date, Path]] = []
        for path in self.data_root.glob("????-??-??_需求工作联系单模板.docx"):
            match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})_需求工作联系单模板\.docx", path.name)
            if match is None or not path.is_file():
                continue
            try:
                effective_date = date.fromisoformat(match.group(1))
            except ValueError:
                continue
            if effective_date <= document_date:
                dated_templates.append((effective_date, path))
        if dated_templates:
            return max(dated_templates, key=lambda item: item[0])[1]
        return self.template_path

    @property
    def template_names(self) -> set[str]:
        """Names of configured and dated templates to exclude from archive scans."""
        names = {self.template_name}
        for path in self.data_root.glob("????-??-??_需求工作联系单模板.docx"):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}_需求工作联系单模板\.docx", path.name):
                names.add(path.name)
        return names
