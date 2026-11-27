"""
Lấy proxy miễn phí cho VietQR bằng swiftshadow (ở luồng nền), chỉ giữ proxy mở được HTTPS.
"""

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Trang HTTPS trung lập để thử proxy có mở được kết nối HTTPS không (trả về IP, rất nhẹ).
HTTPS_CHECK_URL = "https://api.ipify.org"
HTTPS_CHECK_TIMEOUT_SECONDS = 8
# Một lần lấy proxy (gom + thử) quá thời gian này thì coi như treo, lần sau lấy lại từ đầu.
MAX_FETCH_SECONDS = 15 * 60


class FreeProxyPool:
    """
    Nguồn proxy cho HttpClient.set_proxy_supplier: trả proxy đã lấy xong, chưa có thì lấy ở nền.
    """

    def __init__(
        self,
        cache_folder: Path,
        max_proxies: int,
        refresh_seconds: int,
    ):
        self.cache_folder = cache_folder
        self.max_proxies = max_proxies
        self.refresh_seconds = refresh_seconds
        self.lock = threading.Lock()
        self.ready_proxy_urls: list[str] = []
        self.fetch_thread: Optional[threading.Thread] = None
        self.fetch_started_at: Optional[float] = None
        # Mỗi lần lấy có số thứ tự; luồng cũ bị coi là treo mà sau đó mới xong thì kết quả bị bỏ.
        self.fetch_generation = 0

    def take_new_proxies(self) -> list[str]:
        """
        Trả về các proxy mới lấy được (mỗi proxy chỉ trả một lần). Chưa có thì bắt đầu lấy ở nền nếu đã đến lúc.
        """
        with self.lock:
            proxy_urls = self.ready_proxy_urls
            self.ready_proxy_urls = []

        if proxy_urls:
            return proxy_urls

        now = time.monotonic()
        is_fetching = self.fetch_thread is not None and self.fetch_thread.is_alive()
        if is_fetching and self.fetch_started_at is not None and now - self.fetch_started_at < MAX_FETCH_SECONDS:
            return []

        if is_fetching:
            logger.warning("swiftshadow: lần lấy proxy trước chạy quá %d phút, lấy lại từ đầu", MAX_FETCH_SECONDS // 60)
        elif self.fetch_started_at is not None and now - self.fetch_started_at < self.refresh_seconds:
            return []

        self.start_fetch()

        return []

    def start_fetch(self) -> None:
        """
        Bắt đầu một lần lấy proxy ở luồng nền.
        """
        with self.lock:
            self.fetch_generation += 1
            fetch_generation = self.fetch_generation

        self.fetch_started_at = time.monotonic()
        self.fetch_thread = threading.Thread(
            target=self.fetch,
            args=(fetch_generation,),
            name="swiftshadow-fetch",
            daemon=True,
        )
        self.fetch_thread.start()

    def fetch(self, fetch_generation: int) -> None:
        """
        Chạy ở luồng nền: gom proxy bằng swiftshadow, thử HTTPS, rồi để sẵn cho take_new_proxies().
        """
        try:
            from swiftshadow.classes import ProxyInterface
            from swiftshadow.utils import filter_on_target
        except ImportError:
            logger.error("Chưa cài swiftshadow (pip install -r requirements.txt), không lấy được proxy miễn phí")

            return

        quiet_swiftshadow_logger()
        self.cache_folder.mkdir(parents=True, exist_ok=True)
        try:
            proxy_interface = ProxyInterface(
                protocol="http",
                maxProxies=self.max_proxies,
                cachePeriod=max(self.refresh_seconds // 60, 1),
                cacheFolderPath=self.cache_folder,
            )
            candidate_proxies = list(proxy_interface.proxies)
            working_proxies = asyncio.run(
                filter_on_target(
                    HTTPS_CHECK_URL,
                    candidate_proxies,
                    timeout=HTTPS_CHECK_TIMEOUT_SECONDS,
                )
            )
        except Exception as exception:  # thư viện lỗi / không có proxy nào: lần sau lấy lại
            logger.warning("swiftshadow: không lấy được proxy (%s: %s)", type(exception).__name__, exception)

            return

        proxy_urls = [f"http://{proxy.ip}:{proxy.port}" for proxy in working_proxies]
        logger.info(
            "swiftshadow: lấy được %d proxy miễn phí, %d proxy mở được HTTPS",
            len(candidate_proxies),
            len(proxy_urls),
        )
        with self.lock:
            if fetch_generation == self.fetch_generation:
                self.ready_proxy_urls.extend(proxy_urls)


def quiet_swiftshadow_logger() -> None:
    """
    Bỏ bộ in log riêng của swiftshadow (log bị in hai lần), chỉ giữ cảnh báo.
    """
    swiftshadow_logger = logging.getLogger("swiftshadow")
    for handler in list(swiftshadow_logger.handlers):
        swiftshadow_logger.removeHandler(handler)

    swiftshadow_logger.setLevel(logging.WARNING)
