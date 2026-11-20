"""
Điểm chạy chương trình.

PyCharm: mở main.py -> bấm Run (dùng cấu hình trong config.py).
Dòng lệnh:
    python main.py                                  # chạy theo config.py
    python main.py --cities "Hà Nội" --max-companies 50
    python main.py --keywords "xây dựng" "lập trình"   # lọc theo ngành nghề
    python main.py --directory-pages 100            # đọc tối đa 100 trang địa bàn mỗi tỉnh
    python main.py --input danh_sach.csv --sources  # chỉ làm giàu danh sách có sẵn, không tự tìm công ty
    python main.py --no-website --no-registry       # chạy nhanh, bớt nguồn bổ sung
"""

import argparse
import logging
import os
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, TextIO

import config
from lead_crawler.pipeline import ALL_DISCOVERY_SOURCES, Settings, run_crawl

PROJECT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    """
    Đọc tham số dòng lệnh; tham số nào không truyền thì lấy theo config.py.
    """
    argument_parser = argparse.ArgumentParser(description="Thu thập thông tin doanh nghiệp cho MKT")
    argument_parser.add_argument("--cities", nargs="+", help='Khu vực trong config.CITIES, ví dụ: "Hà Nội" "Đà Nẵng"')
    argument_parser.add_argument("--input", help="File CSV danh sách công ty có sẵn (xem input_template.csv)")
    argument_parser.add_argument(
        "--sources",
        nargs="*",
        choices=ALL_DISCOVERY_SOURCES,
        help="Nguồn tự tìm công ty; để trống sau --sources = không tự tìm (chỉ dùng --input)",
    )
    argument_parser.add_argument("--keywords", nargs="+", help="Từ khóa ngành nghề để lọc công ty tự tìm thấy")
    argument_parser.add_argument("--directory-pages", type=int, help="Số trang địa bàn doanhnghiep.me tối đa mỗi tỉnh")
    argument_parser.add_argument("--registry-pages", type=int, help="Số trang tratencongty tối đa mỗi tỉnh")
    argument_parser.add_argument("--max-companies", type=int, help="Dừng sau N doanh nghiệp")
    argument_parser.add_argument("--vietqr", action="store_true", help="Bật tra MST qua VietQR (trạng thái hoạt động, tên pháp lý)")
    argument_parser.add_argument("--no-vietqr", action="store_true", help="Tắt tra MST qua VietQR")
    argument_parser.add_argument("--no-directory-detail", action="store_true", help="Không đọc trang chi tiết doanhnghiep.me")
    argument_parser.add_argument("--no-registry", action="store_true", help="Không tra tratencongty.com (người đại diện pháp luật)")
    argument_parser.add_argument("--no-website", action="store_true", help="Không đọc website công ty")
    argument_parser.add_argument("--output", help="Thư mục kết quả")

    return argument_parser.parse_args()


def build_settings(arguments: argparse.Namespace) -> Settings:
    """
    Gộp config.py với tham số dòng lệnh.
    """
    cities = config.CITIES
    if arguments.cities:
        unknown_cities = [city for city in arguments.cities if city not in config.CITIES]
        if unknown_cities:
            sys.exit(f"Khu vực không có trong config.CITIES: {unknown_cities}")

        cities = {city: config.CITIES[city] for city in arguments.cities}

    output_dir = Path(arguments.output or config.OUTPUT_DIR)
    if not output_dir.is_absolute():
        output_dir = PROJECT_DIR / output_dir

    input_text = arguments.input or config.INPUT_FILE
    input_file = Path(input_text) if input_text else None
    if input_file is not None and not input_file.is_absolute():
        input_file = PROJECT_DIR / input_file

    discovery_sources = config.DISCOVERY_SOURCES if arguments.sources is None else arguments.sources

    return Settings(
        cities=cities,
        discovery_sources=list(discovery_sources),
        input_file=input_file,
        directory_max_pages_per_city=arguments.directory_pages or config.DIRECTORY_MAX_PAGES_PER_CITY,
        registry_max_pages_per_city=arguments.registry_pages or config.REGISTRY_MAX_PAGES_PER_CITY,
        keywords=arguments.keywords or config.KEYWORDS,
        max_companies=arguments.max_companies or config.MAX_COMPANIES,
        use_vietqr_tax_lookup=(config.USE_VIETQR_TAX_LOOKUP or arguments.vietqr) and not arguments.no_vietqr,
        vietqr_wait_if_rate_limited=config.VIETQR_WAIT_IF_RATE_LIMITED,
        doanhnghiep_me_fetch_detail=config.DOANHNGHIEP_ME_FETCH_DETAIL and not arguments.no_directory_detail,
        use_tratencongty=config.USE_TRATENCONGTY and not arguments.no_registry,
        tratencongty_fetch_detail=config.TRATENCONGTY_FETCH_DETAIL,
        tratencongty_search_by_name=config.TRATENCONGTY_SEARCH_BY_NAME,
        enrich_from_website=config.ENRICH_FROM_WEBSITE and not arguments.no_website,
        vietqr_delay_seconds=config.VIETQR_DELAY_SECONDS,
        doanhnghiep_me_delay_seconds=config.DOANHNGHIEP_ME_DELAY_SECONDS,
        tratencongty_delay_seconds=config.TRATENCONGTY_DELAY_SECONDS,
        website_delay_seconds=config.WEBSITE_DELAY_SECONDS,
        website_max_pages=config.WEBSITE_MAX_PAGES,
        request_timeout_seconds=config.REQUEST_TIMEOUT_SECONDS,
        max_retries=config.MAX_RETRIES,
        user_agent=config.USER_AGENT,
        output_dir=output_dir,
    )


def setup_logging(output_dir: Path) -> None:
    """
    Log ra màn hình và file output/crawl.log (tự xoay vòng: tối đa 5 file x 10 MB để không đầy ổ server).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                output_dir / "crawl.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            ),
        ],
    )


def acquire_run_lock(output_dir: Path) -> Optional[TextIO]:
    """
    Khóa thư mục output để không có 2 tiến trình cùng ghi một file CSV
    (vd. cron gọi lần mới khi lần trước chưa chạy xong). Hệ điều hành tự nhả khóa khi tiến trình kết thúc.
    Trả về None nếu đang có tiến trình khác giữ khóa.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    lock_file = (output_dir / ".run.lock").open("a+")
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()

        return None

    return lock_file


def handle_stop_signal(
    signal_number,
    frame,
) -> None:
    """
    Server gửi SIGTERM khi dừng dịch vụ (systemctl stop, docker stop): dừng giống Ctrl+C để đóng file gọn gàng.
    """
    raise KeyboardInterrupt


def main() -> int:
    """
    Chạy chương trình; trả về mã thoát (0 = thành công) để cron / systemd / Docker theo dõi.
    """
    # Console Windows mặc định cp1252 không in được tiếng Việt.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    arguments = parse_args()
    settings = build_settings(arguments)
    setup_logging(settings.output_dir)
    logger = logging.getLogger("main")
    signal.signal(signal.SIGTERM, handle_stop_signal)

    # Giữ biến run_lock tới hết hàm main: file còn mở thì khóa còn hiệu lực.
    run_lock = acquire_run_lock(settings.output_dir)
    if run_lock is None:
        logger.error("Đang có một lần chạy khác dùng thư mục %s, thoát.", settings.output_dir)

        return 2

    try:
        written_count = run_crawl(settings)
    except KeyboardInterrupt:
        logger.warning("Đã dừng. Chạy lại để tiếp tục từ chỗ dừng.")

        return 130

    logger.info(
        "Xong. Ghi mới %d doanh nghiệp. Kết quả: %s và %s",
        written_count,
        settings.output_dir / "companies.csv",
        settings.output_dir / "contacts.csv",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
