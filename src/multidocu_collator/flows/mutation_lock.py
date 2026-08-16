"""串行化由本地 HTML 发起的资料目录写操作。"""

from __future__ import annotations

import threading


RECORD_MUTATION_LOCK = threading.Lock()
