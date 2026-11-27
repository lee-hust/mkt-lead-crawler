"""
HTTP client dùng chung: tuân thủ robots.txt, giãn cách theo host, thử lại khi lỗi; gặp 403 thì dừng host.
Host có nguồn proxy (VietQR) được gọi xoay vòng qua IP máy và từng proxy; đường nào bị 429 thì nghỉ riêng.
"""

import json
import logging
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
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
# Proxy miễn phí thường chậm / chết: chờ phản hồi tối đa bấy nhiêu giây (gọi trực tiếp vẫn theo cấu hình).
PROXY_TIMEOUT_SECONDS = 10
# Proxy lỗi kết nối thì nghỉ proxy đó 60 giây; lỗi liên tiếp bấy nhiêu lần thì bỏ hẳn.
PROXY_ERROR_COOLDOWN_SECONDS = 60
MAX_PROXY_FAILURES = 2
# Proxy bị báo quá tải mà site không nói phải chờ bao lâu (không có Retry-After) thì nghỉ proxy đó bấy nhiêu giây.
PROXY_RATE_LIMIT_COOLDOWN_SECONDS = 60
# Mỗi URL thử tối đa max_retries x số đường (tính tối đa bấy nhiêu đường), để proxy hỏng không kéo dài một lượt.
MAX_ROUTES_PER_FETCH = 4
# Mã 407 (proxy báo sai tài khoản) trong thông báo lỗi; không khớp số 407 nằm trong MST (vd. 0101234567-407).
PROXY_AUTH_ERROR_PATTERN = re.compile(r"(?<![\d-])407(?!\d)")


@dataclass(eq=False)
class Route:
    """
    Một đường gọi tới host: trực tiếp từ IP máy chạy tool (proxy_url = None) hoặc qua một proxy.
    """

    host: str
    # Khóa lưu khoảng nghỉ, lần gọi cuối, thời gian bị bắt chờ. Đường trực tiếp dùng chính tên host.
    key: str
    # Tên ngắn trong log: "IP máy chạy tool", "proxy 1"...
    name: str
    proxy_url: Optional[str] = None
    # Số lần lỗi kết nối liên tiếp qua proxy này.
    failure_count: int = 0

    @property
    def label(self) -> str:
        """
        Tên hiển thị trong log, kèm host:port của proxy.
        """
        if self.proxy_url is None:
            return self.name

        return f"{self.name} ({describe_proxy(self.proxy_url)})"

    @property
    def proxies(self) -> Optional[dict[str, str]]:
        """
        Tham số proxies cho requests; None = gọi trực tiếp.
        """
        if self.proxy_url is None:
            return None

        return {
            "http": self.proxy_url,
            "https": self.proxy_url,
        }


def describe_proxy(proxy_url: str) -> str:
    """
    Tên proxy để ghi log: chỉ giữ host:port, bỏ tài khoản / mật khẩu nếu có.
    """
    parsed_url = urlparse(proxy_url)

    return f"{parsed_url.hostname}:{parsed_url.port}"


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
        # Khoảng nghỉ, lần gọi cuối, thời gian bị bắt chờ: lưu theo Route.key (đường trực tiếp = tên host).
        self.host_delays: dict[str, float] = {}
        self.last_request_times: dict[str, float] = {}
        self.cooldown_until: dict[str, float] = {}
        self.robot_file_parsers: dict[str, Optional[RobotFileParser]] = {}
        self.blocked_hosts: set[str] = set()
        self.host_routes: dict[str, list[Route]] = {}
        # Nguồn proxy của từng host: hàm trả về proxy mới (có thể rỗng) và số proxy tối thiểu cần giữ.
        self.proxy_suppliers: dict[str, tuple[Callable[[], list[str]], int]] = {}
        # Proxy đã bỏ trong lần chạy này, không thêm lại.
        self.dropped_proxy_urls: dict[str, set[str]] = {}
        self.proxy_counters: dict[str, int] = {}

    def set_host_delay(
        self,
        host: str,
        delay_seconds: float,
    ) -> None:
        """
        Đặt khoảng nghỉ tối thiểu giữa hai request tới cùng một host (áp dụng riêng cho từng đường gọi).
        """
        host = host.lower()
        self.host_delays[host] = max(delay_seconds, self.host_delays.get(host, 0))

    def set_proxy_supplier(
        self,
        host: str,
        proxy_supplier: Callable[[], list[str]],
        min_proxy_routes: int,
    ) -> None:
        """
        Gọi host qua proxy, bên cạnh IP máy. proxy_supplier() trả proxy mới (có thể rỗng), được hỏi khi thiếu proxy.
        """
        host = host.lower()
        self.proxy_suppliers[host] = (proxy_supplier, min_proxy_routes)

    def get_routes(self, host: str) -> list[Route]:
        """
        Các đường đang dùng được để gọi host. Mặc định chỉ có một đường trực tiếp.
        """
        host = host.lower()
        routes = self.host_routes.get(host)
        if routes is None:
            routes = [
                Route(
                    host=host,
                    key=host,
                    name="IP máy chạy tool",
                )
            ]
            self.host_routes[host] = routes

        return routes

    def add_proxy_routes(
        self,
        host: str,
        proxy_urls: list[str],
    ) -> int:
        """
        Thêm proxy làm đường gọi host (bỏ qua proxy đang dùng hoặc đã bị bỏ). Trả về số proxy thêm được.
        """
        host = host.lower()
        routes = self.get_routes(host)
        known_proxy_urls = {route.proxy_url for route in routes} | self.dropped_proxy_urls.get(host, set())
        added_count = 0
        for proxy_url in proxy_urls:
            if proxy_url in known_proxy_urls:
                continue

            known_proxy_urls.add(proxy_url)
            proxy_number = self.proxy_counters.get(host, 0) + 1
            self.proxy_counters[host] = proxy_number
            routes.append(
                Route(
                    host=host,
                    key=f"{host}#proxy{proxy_number}",
                    name=f"proxy {proxy_number}",
                    proxy_url=proxy_url,
                )
            )
            added_count += 1

        if added_count:
            logger.info(
                "%s: thêm %d proxy, đang dùng %d proxy + %s",
                host,
                added_count,
                self.count_proxy_routes(host),
                "IP máy chạy tool" if any(route.proxy_url is None for route in routes) else "không dùng IP máy",
            )

        return added_count

    def count_proxy_routes(self, host: str) -> int:
        """
        Số proxy đang dùng được cho host.
        """
        return sum(1 for route in self.get_routes(host) if route.proxy_url is not None)

    def is_blocked(self, host: str) -> bool:
        """
        Host đã từ chối truy cập (403 hoặc 429 kéo dài) trong lần chạy này hay chưa.
        """
        return host.lower() in self.blocked_hosts

    def is_cooling_down(self, host: str) -> bool:
        """
        Mọi đường gọi host đều đang trong thời gian bị yêu cầu chờ (sau 429/503) hay không.
        """
        now = time.monotonic()

        return all(self._is_route_cooling(route, now) for route in self.get_routes(host))

    def get_text(
        self,
        url: str,
        wait_if_rate_limited: bool = False,
    ) -> Optional[str]:
        """
        Tải trang HTML; None nếu robots.txt cấm, lỗi hoặc không phải HTML. wait_if_rate_limited: chờ khi bị 429.
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
        Gọi API trả JSON; None nếu lỗi. wait_if_rate_limited: chờ khi bị 429.
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
        Tải và phân tích robots.txt (qua đường gọi đầu tiên của host); đồng thời áp dụng Crawl-delay nếu site yêu cầu.
        """
        host = urlparse(base_url).netloc.lower()
        route = self.get_routes(host)[0]
        self._wait_for_route(route)
        try:
            response = self.session.get(
                base_url + "/robots.txt",
                timeout=self._timeout_of(route),
                proxies=route.proxies,
            )
        except requests.RequestException:
            return None
        finally:
            self.last_request_times[route.key] = time.monotonic()

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
        Tải URL với retry, chỉ trả nội dung khi HTTP 200; mỗi lần thử chọn đường gọi đang rảnh.
        """
        host = urlparse(url).netloc.lower()
        if not host or host in self.blocked_hosts:
            return None

        route = self._choose_route(
            host,
            wait_if_rate_limited,
        )
        if route is None:
            return None

        # Nguồn bổ sung còn phải chờ lâu thì bỏ qua lần này.
        if not wait_if_rate_limited and self._remaining_delay(route) > MAX_ENRICHMENT_WAIT_SECONDS:
            return None

        if not self.is_allowed(url):
            logger.info("robots.txt không cho phép, bỏ qua: %s", url)

            return None

        max_attempts = self.max_retries * min(max(len(self.get_routes(host)), 1), MAX_ROUTES_PER_FETCH)
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                route = self._choose_route(
                    host,
                    wait_if_rate_limited,
                )
                if route is None:
                    return None

            self._wait_for_route(route)
            try:
                response = self.session.get(
                    url,
                    timeout=self._timeout_of(route),
                    stream=True,
                    proxies=route.proxies,
                )
            except requests.RequestException as request_exception:
                self.last_request_times[route.key] = time.monotonic()
                if route.proxy_url is not None:
                    self._handle_proxy_error(
                        route,
                        request_exception,
                    )
                    continue

                logger.warning("Lỗi kết nối %s (lần %d/%d): %s", url, attempt, max_attempts, request_exception)
                time.sleep(5 * min(attempt, self.max_retries))
                continue

            self.last_request_times[route.key] = time.monotonic()
            route.failure_count = 0
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

            if status_code == 407 and route.proxy_url is not None:
                self._drop_route(
                    route,
                    "proxy đòi tài khoản (407)",
                )
                continue

            if status_code == 403:
                if self._handle_forbidden(route):
                    continue

                return None

            if status_code in (429, 503):
                has_retry_after = response.headers.get("Retry-After", "").isdigit()
                wait_seconds = self._retry_after_seconds(response, 60 * min(attempt, self.max_retries))
                if route.proxy_url is not None and not has_retry_after:
                    wait_seconds = PROXY_RATE_LIMIT_COOLDOWN_SECONDS

                # Không chờ: bỏ qua host tới hết thời gian chờ; site không ghi Retry-After thì giảm tốc.
                if not wait_if_rate_limited and not has_retry_after and route.proxy_url is None:
                    self._slow_down(route)

                self.cooldown_until[route.key] = time.monotonic() + wait_seconds

                # Còn đường khác (proxy khác / IP máy chạy tool) đang rảnh thì gọi tiếp qua đường đó.
                free_in_seconds = self._seconds_until_free(host)
                if free_in_seconds <= 0:
                    logger.debug(
                        "%s báo quá tải (%d) qua %s: nghỉ đường này %d giây, gọi tiếp qua đường khác",
                        host,
                        status_code,
                        route.label,
                        wait_seconds,
                    )
                    continue

                resume_at = datetime.now() + timedelta(seconds=free_in_seconds)
                if not wait_if_rate_limited:
                    logger.warning(
                        "%s báo quá tải (%d), yêu cầu chờ %d giây: tạm bỏ qua nguồn này đến %s, các nguồn khác vẫn chạy",
                        host,
                        status_code,
                        free_in_seconds,
                        resume_at.strftime("%H:%M:%S"),
                    )

                    return None

                # Chế độ chờ: chờ đúng thời gian site yêu cầu rồi gọi lại.
                logger.warning(
                    "%s báo quá tải (%d), chờ %d giây (đến %s) rồi gọi lại",
                    host,
                    status_code,
                    free_in_seconds,
                    resume_at.strftime("%H:%M:%S"),
                )
                time.sleep(free_in_seconds)
                continue

            if status_code >= 500:
                time.sleep(10 * min(attempt, self.max_retries))
                continue

            return None

        if host not in self.blocked_hosts:
            logger.warning("Bỏ qua sau %d lần thử: %s", max_attempts, url)

        return None

    def _choose_route(
        self,
        host: str,
        wait_if_rate_limited: bool,
    ) -> Optional[Route]:
        """
        Chọn đường rảnh sớm tới lượt nhất (bằng nhau thì đường lâu chưa dùng). Hết đường rảnh: chế độ chờ thì ngủ, không thì None.
        """
        if host in self.blocked_hosts:
            return None

        self._refill_proxy_routes(host)
        routes = self.get_routes(host)
        if not routes:
            return None

        now = time.monotonic()
        free_routes = [route for route in routes if not self._is_route_cooling(route, now)]
        if free_routes:
            return min(
                free_routes,
                key=lambda route: (
                    self._remaining_delay(route),
                    self.last_request_times.get(route.key, -math.inf),
                ),
            )

        if not wait_if_rate_limited:
            return None

        route = min(
            routes,
            key=lambda route: self.cooldown_until[route.key],
        )
        remaining_seconds = self.cooldown_until[route.key] - now
        logger.info("Chờ %d giây theo yêu cầu của %s rồi đọc tiếp", remaining_seconds, host)
        time.sleep(max(remaining_seconds, 0))

        return route

    def _refill_proxy_routes(self, host: str) -> None:
        """
        Host có nguồn proxy mà số proxy đang dùng được ít hơn mức tối thiểu thì lấy thêm.
        """
        proxy_supplier_entry = self.proxy_suppliers.get(host)
        if proxy_supplier_entry is None:
            return

        proxy_supplier, min_proxy_routes = proxy_supplier_entry
        if self.count_proxy_routes(host) >= min_proxy_routes:
            return

        try:
            proxy_urls = proxy_supplier()
        except Exception as exception:  # nguồn proxy lỗi không được làm dừng tool
            logger.warning("%s: lỗi khi lấy thêm proxy: %s", host, exception)

            return

        if proxy_urls:
            self.add_proxy_routes(
                host,
                proxy_urls,
            )

    def _handle_forbidden(self, route: Route) -> bool:
        """
        403: bỏ proxy bị từ chối; IP máy bị từ chối mà còn proxy thì bỏ IP máy, không thì dừng host. True nếu còn đường.
        """
        host = route.host
        if route.proxy_url is not None:
            self._drop_route(
                route,
                "bị từ chối (403)",
            )

            return host not in self.blocked_hosts

        if self.count_proxy_routes(host) > 0:
            self._drop_route(
                route,
                "bị từ chối (403), chạy tiếp bằng proxy",
            )

            return host not in self.blocked_hosts

        logger.error(
            "%s trả về 403 (từ chối truy cập). Dừng truy cập host này trong lần chạy hiện tại.",
            host,
        )
        self.blocked_hosts.add(host)

        return False

    def _handle_proxy_error(
        self,
        route: Route,
        request_exception: requests.RequestException,
    ) -> None:
        """
        Lỗi qua proxy: 407 thì bỏ; lỗi khác nghỉ 60 giây, lỗi MAX_PROXY_FAILURES lần liên tiếp thì bỏ.
        """
        if PROXY_AUTH_ERROR_PATTERN.search(str(request_exception)):
            self._drop_route(
                route,
                "proxy đòi tài khoản (407)",
            )

            return

        route.failure_count += 1
        if route.failure_count >= MAX_PROXY_FAILURES:
            self._drop_route(
                route,
                f"lỗi kết nối {route.failure_count} lần liên tiếp ({type(request_exception).__name__})",
            )

            return

        self.cooldown_until[route.key] = time.monotonic() + PROXY_ERROR_COOLDOWN_SECONDS
        logger.debug(
            "Lỗi kết nối qua %s (%s), nghỉ proxy này %d giây",
            route.label,
            type(request_exception).__name__,
            PROXY_ERROR_COOLDOWN_SECONDS,
        )

    def _drop_route(
        self,
        route: Route,
        reason: str,
    ) -> None:
        """
        Bỏ một đường gọi trong lần chạy này; hết đường và không lấy thêm được proxy thì dừng host.
        """
        routes = self.get_routes(route.host)
        if route in routes:
            routes.remove(route)

        if route.proxy_url is not None:
            self.dropped_proxy_urls.setdefault(route.host, set()).add(route.proxy_url)
            logger.info(
                "%s: bỏ %s, %s (còn %d proxy)",
                route.host,
                route.label,
                reason,
                self.count_proxy_routes(route.host),
            )
        else:
            logger.warning("%s: không dùng %s nữa, %s", route.host, route.label, reason)

        if not routes:
            self._refill_proxy_routes(route.host)

        if not routes:
            logger.error(
                "%s: không còn đường gọi nào dùng được. Dừng truy cập host này trong lần chạy hiện tại.",
                route.host,
            )
            self.blocked_hosts.add(route.host)

    def _is_route_cooling(
        self,
        route: Route,
        now: float,
    ) -> bool:
        """
        Đường gọi này còn trong thời gian bị yêu cầu chờ (sau 429/503 hoặc proxy lỗi kết nối) hay không.
        """
        until = self.cooldown_until.get(route.key)

        return until is not None and now < until

    def _seconds_until_free(self, host: str) -> int:
        """
        Còn bao nhiêu giây nữa mới có ít nhất một đường gọi host hết bị bắt chờ (0 = đang có đường rảnh).
        """
        routes = self.get_routes(host)
        if not routes:
            return 0

        now = time.monotonic()
        remaining_seconds = min(self.cooldown_until.get(route.key, now) - now for route in routes)

        return max(math.ceil(remaining_seconds), 0)

    def _remaining_delay(self, route: Route) -> float:
        """
        Còn bao nhiêu giây nữa mới được gửi request tiếp theo qua đường này.
        """
        last_request_time = self.last_request_times.get(route.key)
        if last_request_time is None:
            return 0

        return max(self._delay_of(route) - (time.monotonic() - last_request_time), 0)

    def _delay_of(self, route: Route) -> float:
        """
        Khoảng nghỉ của đường gọi: đường đã bị giảm tốc thì dùng khoảng nghỉ riêng, không thì theo host.
        """
        if route.key in self.host_delays:
            return self.host_delays[route.key]

        return self.host_delays.get(route.host, self.default_delay_seconds)

    def _timeout_of(self, route: Route) -> float:
        """
        Thời gian chờ phản hồi: qua proxy thì ngắn hơn, để proxy chết không làm chậm cả lượt tra.
        """
        if route.proxy_url is None:
            return self.timeout_seconds

        return min(self.timeout_seconds, PROXY_TIMEOUT_SECONDS)

    def _slow_down(self, route: Route) -> None:
        """
        Sau mỗi lần bị báo quá tải, gấp đôi khoảng nghỉ của đường gọi đó (tối đa MAX_HOST_DELAY_SECONDS).
        """
        current_delay = self._delay_of(route)
        new_delay = min(current_delay * 2, MAX_HOST_DELAY_SECONDS)
        if new_delay > current_delay:
            self.host_delays[route.key] = new_delay
            logger.info("Giảm tốc %s: khoảng nghỉ %.1f -> %.1f giây", route.host, current_delay, new_delay)

    def _wait_for_route(self, route: Route) -> None:
        """
        Ngủ cho đủ khoảng delay kể từ request trước qua cùng đường gọi.
        """
        remaining_seconds = self._remaining_delay(route)
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
