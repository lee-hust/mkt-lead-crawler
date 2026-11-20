"""
HTTP client dùng chung cho mọi nguồn: tôn trọng robots.txt, giãn cách request theo
từng host, thử lại khi lỗi tạm thời. Gặp 403 / chặn bot thì dừng host đó, không tìm
cách vượt qua.
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 5 * 1024 * 1024

# Nguồn bổ sung còn phải chờ lâu hơn mức này mới tới lượt thì bỏ qua lần gọi đó.
MAX_ENRICHMENT_WAIT_SECONDS = 5
# Khoảng nghỉ tối đa sau khi tự giảm tốc.
MAX_HOST_DELAY_SECONDS = 60


class HttpClient:
    """
    Bọc requests.Session, thêm kiểm tra robots.txt, delay theo host và retry.
    """

    def __init__(
        self,
        user_agent: str,
        default_delay_seconds: float,
        timeout_seconds: float,
        max_retries: int,
    ):
        self.user_agent = user_agent
        self.default_delay_seconds = default_delay_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
            }
        )
        self.host_delays: dict[str, float] = {}
        self.last_request_times: dict[str, float] = {}
        self.robot_file_parsers: dict[str, Optional[RobotFileParser]] = {}
        self.blocked_hosts: set[str] = set()
        self.cooldown_until: dict[str, float] = {}

    def set_host_delay(
        self,
        host: str,
        delay_seconds: float,
    ) -> None:
        """
        Đặt khoảng nghỉ tối thiểu giữa hai request tới cùng một host.
        """
        host = host.lower()
        self.host_delays[host] = max(delay_seconds, self.host_delays.get(host, 0))

    def is_blocked(self, host: str) -> bool:
        """
        Host đã từ chối truy cập (403 hoặc 429 kéo dài) trong lần chạy này hay chưa.
        """
        return host.lower() in self.blocked_hosts

    def is_cooling_down(self, host: str) -> bool:
        """
        Host đang trong thời gian bị yêu cầu chờ (sau 429/503) hay không.
        """
        until = self.cooldown_until.get(host.lower())

        return until is not None and time.monotonic() < until

    def get_text(
        self,
        url: str,
        wait_if_rate_limited: bool = False,
    ) -> Optional[str]:
        """
        Tải một trang HTML. Trả về None nếu robots.txt cấm, lỗi mạng, hoặc không phải HTML.
        wait_if_rate_limited=True: chờ khi site báo quá tải (dùng cho trang danh sách — bỏ qua thì mất công ty).
        Mặc định False: site đang bắt chờ thì bỏ qua request này để các nguồn khác chạy tiếp.
        """
        return self._fetch(
            url,
            False,
            wait_if_rate_limited,
        )

    def get_json(
        self,
        url: str,
        wait_if_rate_limited: bool = False,
    ) -> Optional[dict]:
        """
        Gọi một API trả JSON. Trả về None nếu lỗi.
        wait_if_rate_limited=True: API báo quá tải thì chờ đúng thời gian yêu cầu rồi gọi lại;
        mặc định False: bỏ qua lần gọi này để các nguồn khác chạy tiếp.
        """
        text = self._fetch(
            url,
            True,
            wait_if_rate_limited,
        )
        if text is None:
            return None

        try:
            return json.loads(text)
        except ValueError:
            logger.warning("Phản hồi không phải JSON: %s", url)

            return None

    def is_allowed(self, url: str) -> bool:
        """
        Kiểm tra robots.txt của site có cho phép tải URL này không.
        """
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        if base_url not in self.robot_file_parsers:
            self.robot_file_parsers[base_url] = self._load_robots(base_url)

        robot_file_parser = self.robot_file_parsers[base_url]
        if robot_file_parser is None:
            return True

        return robot_file_parser.can_fetch(
            self.user_agent,
            url,
        )

    def _load_robots(self, base_url: str) -> Optional[RobotFileParser]:
        """
        Tải và phân tích robots.txt; đồng thời áp dụng Crawl-delay nếu site yêu cầu.
        """
        host = urlparse(base_url).netloc.lower()
        self._wait_for_host(host)
        try:
            response = self.session.get(
                base_url + "/robots.txt",
                timeout=self.timeout_seconds,
            )
        except requests.RequestException:
            return None
        finally:
            self.last_request_times[host] = time.monotonic()

        robot_file_parser = RobotFileParser()
        if response.status_code in (401, 403):
            robot_file_parser.disallow_all = True

            return robot_file_parser

        if response.status_code != 200:
            return None

        robot_file_parser.parse(response.text.splitlines())
        crawl_delay = robot_file_parser.crawl_delay(self.user_agent)
        if crawl_delay:
            self.set_host_delay(
                host,
                float(crawl_delay),
            )
            logger.info("%s yêu cầu Crawl-delay %s giây", host, crawl_delay)

        return robot_file_parser

    def _fetch(
        self,
        url: str,
        expect_json: bool,
        wait_if_rate_limited: bool,
    ) -> Optional[str]:
        """
        Tải URL với retry. Chỉ trả về nội dung khi HTTP 200.
        """
        host = urlparse(url).netloc.lower()
        if not host or host in self.blocked_hosts:
            return None

        if self.is_cooling_down(host):
            if not wait_if_rate_limited:
                return None

            remaining_seconds = self.cooldown_until[host] - time.monotonic()
            logger.info("Chờ %d giây theo yêu cầu của %s rồi đọc tiếp", remaining_seconds, host)
            time.sleep(max(remaining_seconds, 0))

        # Nguồn bổ sung mà còn phải chờ lâu mới tới lượt (do đã bị giảm tốc) thì bỏ qua lần này,
        # không bắt cả chương trình đứng chờ.
        if not wait_if_rate_limited and self._remaining_delay(host) > MAX_ENRICHMENT_WAIT_SECONDS:
            return None

        if not self.is_allowed(url):
            logger.info("robots.txt không cho phép, bỏ qua: %s", url)

            return None

        for attempt in range(1, self.max_retries + 1):
            self._wait_for_host(host)
            try:
                response = self.session.get(
                    url,
                    timeout=self.timeout_seconds,
                    stream=True,
                )
            except requests.RequestException as request_exception:
                self.last_request_times[host] = time.monotonic()
                logger.warning("Lỗi kết nối %s (lần %d/%d): %s", url, attempt, self.max_retries, request_exception)
                time.sleep(5 * attempt)
                continue

            self.last_request_times[host] = time.monotonic()
            status_code = response.status_code

            if status_code == 200:
                content_type = response.headers.get("Content-Type", "").lower()
                if not expect_json and content_type and "html" not in content_type:
                    response.close()

                    return None

                body = self._read_limited(response)
                encoding = response.encoding
                if not encoding or encoding.lower() == "iso-8859-1":
                    encoding = "utf-8"

                return body.decode(
                    encoding,
                    errors="replace",
                )

            response.close()

            if status_code in (404, 410):
                return None

            if status_code == 403:
                logger.error(
                    "%s trả về 403 (từ chối truy cập). Dừng truy cập host này trong lần chạy hiện tại.",
                    host,
                )
                self.blocked_hosts.add(host)

                return None

            if status_code in (429, 503):
                wait_seconds = self._retry_after_seconds(response, 60 * attempt)

                # Chế độ không chờ: tạm bỏ qua host đến hết thời gian bị yêu cầu chờ, đồng thời giảm tốc host đó.
                if not wait_if_rate_limited:
                    self._slow_down(host)
                    self.cooldown_until[host] = time.monotonic() + wait_seconds
                    resume_at = datetime.now() + timedelta(seconds=wait_seconds)
                    logger.warning(
                        "%s báo quá tải (%d), yêu cầu chờ %d giây: tạm bỏ qua nguồn này đến %s, các nguồn khác vẫn chạy",
                        host,
                        status_code,
                        wait_seconds,
                        resume_at.strftime("%H:%M:%S"),
                    )

                    return None

                # Chế độ chờ (trang danh sách, hoặc VietQR khi bật chờ): chờ đúng thời gian site yêu cầu rồi gọi lại.
                # Không giảm tốc thêm, vì thời gian chờ site đưa ra đã đủ để hết bị giới hạn.
                resume_at = datetime.now() + timedelta(seconds=wait_seconds)
                logger.warning(
                    "%s báo quá tải (%d), chờ %d giây (đến %s) rồi gọi lại",
                    host,
                    status_code,
                    wait_seconds,
                    resume_at.strftime("%H:%M:%S"),
                )
                time.sleep(wait_seconds)
                continue

            if status_code >= 500:
                time.sleep(10 * attempt)
                continue

            return None

        if host not in self.blocked_hosts:
            logger.warning("Bỏ qua sau %d lần thử: %s", self.max_retries, url)

        return None

    def _remaining_delay(self, host: str) -> float:
        """
        Còn bao nhiêu giây nữa mới được gửi request tiếp theo tới host.
        """
        last_request_time = self.last_request_times.get(host)
        if last_request_time is None:
            return 0

        delay_seconds = self.host_delays.get(host, self.default_delay_seconds)

        return max(delay_seconds - (time.monotonic() - last_request_time), 0)

    def _slow_down(self, host: str) -> None:
        """
        Sau mỗi lần bị báo quá tải, gấp đôi khoảng nghỉ của host (tối đa MAX_HOST_DELAY_SECONDS).
        """
        current_delay = self.host_delays.get(host, self.default_delay_seconds)
        new_delay = min(current_delay * 2, MAX_HOST_DELAY_SECONDS)
        if new_delay > current_delay:
            self.host_delays[host] = new_delay
            logger.info("Giảm tốc %s: khoảng nghỉ %.1f -> %.1f giây", host, current_delay, new_delay)

    def _wait_for_host(self, host: str) -> None:
        """
        Ngủ cho đủ khoảng delay kể từ request trước tới cùng host.
        """
        delay_seconds = self.host_delays.get(host, self.default_delay_seconds)
        last_request_time = self.last_request_times.get(host)
        if last_request_time is None:
            return

        remaining_seconds = delay_seconds - (time.monotonic() - last_request_time)
        if remaining_seconds > 0:
            time.sleep(remaining_seconds)

    @staticmethod
    def _read_limited(response: requests.Response) -> bytes:
        """
        Đọc nội dung tối đa MAX_BODY_BYTES để tránh tải nhầm file quá lớn.
        """
        chunks = []
        total_bytes = 0
        for chunk in response.iter_content(chunk_size=65536):
            chunks.append(chunk)
            total_bytes += len(chunk)
            if total_bytes >= MAX_BODY_BYTES:
                break

        response.close()

        return b"".join(chunks)

    @staticmethod
    def _retry_after_seconds(
        response: requests.Response,
        default_seconds: int,
    ) -> int:
        """
        Đọc header Retry-After (nếu có), giới hạn tối đa 10 phút.
        """
        retry_after = response.headers.get("Retry-After", "")
        if retry_after.isdigit():
            return min(int(retry_after), 600)

        return default_seconds
