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
    local_ai_base_url: str = "http://127.0.0.1:8080/v1"
    local_ai_model: str = "Qwen_Qwen2.5-VL-7B-Instruct-Q4_K_S.gguf"
    local_ai_autostart: bool = True
    local_ai_server_path: str = ""
    local_ai_model_path: str = ""
    local_ai_mmproj_path: str = ""
    local_ai_n_gpu_layers: int = 999
    local_ai_startup_timeout_sec: int = 180
    local_ai_startup_poll_interval_sec: float = 1.0
    local_ai_request_timeout_sec: int = 180
    local_ai_stdout_log_path: str = "log/llama_server.out.log"
    local_ai_stderr_log_path: str = "log/llama_server.err.log"
    local_ai_extra_dll_dirs: str = ""

    @property
    def json_path(self) -> Path:
        return self.data_root / self.json_name

    @property
    def html_path(self) -> Path:
        return self.data_root / self.html_name

    @property
    def template_path(self) -> Path:
        return self.data_root / self.template_name
