"""
Điểm chạy chương trình. PyCharm: Run main.py (theo config.py); dòng lệnh: python main.py --help.
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
from lead_crawler.vietqr_backfill import run_vietqr_backfill

PROJECT_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    """
    Đọc tham số dòng lệnh; tham số nào không truyền thì lấy theo config.py.
    """
    argument_parser = argparse.ArgumentParser(description="Thu thập thông tin doanh nghiệp cho MKT")
    argument_parser.add_argument(
        "--cities",
        nargs="+",
        help='Tỉnh/TP (địa giới mới) trong config.ALL_CITIES, vd. "Hà Nội" "Cần Thơ"; "all" = mọi tỉnh trong ALL_CITIES',
    )
    argument_parser.add_argument("--input", help="File CSV danh sách công ty có sẵn (xem input_template.csv)")
    argument_parser.add_argument(
        "--sources",
        nargs="*",
        choices=ALL_DISCOVERY_SOURCES,
        help="Nguồn tự tìm công ty; để trống sau --sources = không tự tìm (chỉ dùng --input)",
    )
    argument_parser.add_argument("--keywords", nargs="+", help="Từ khóa ngành nghề để lọc công ty tự tìm thấy")
    argument_parser.add_argument("--directory-pages", type=int, help="Số trang danh sách infodoanhnghiep tối đa mỗi tỉnh")
    argument_parser.add_argument("--registry-pages", type=int, help="Số trang tratencongty tối đa mỗi tỉnh")
    argument_parser.add_argument("--max-companies", type=int, help="Dừng sau N doanh nghiệp")
    argument_parser.add_argument("--vietqr", action="store_true", help="Bật tra MST qua VietQR (trạng thái hoạt động, tên pháp lý)")
    argument_parser.add_argument("--no-vietqr", action="store_true", help="Tắt tra MST qua VietQR")
    argument_parser.add_argument(
        "--vietqr-backfill",
        action="store_true",
        help="Chỉ chạy giai đoạn 2: tra bù VietQR cho công ty còn thiếu trong companies.csv, không cào thêm",
    )
    argument_parser.add_argument(
        "--no-vietqr-backfill",
        action="store_true",
        help="Cào xong thì dừng, không tự tra bù VietQR (giai đoạn 2)",
    )
    argument_parser.add_argument(
        "--vietqr-free-proxies",
        action="store_true",
        help="Tra VietQR xoay vòng qua proxy miễn phí lấy bằng swiftshadow (xem config.VIETQR_FREE_PROXIES)",
    )
    argument_parser.add_argument("--no-infodoanhnghiep", action="store_true", help="Không tra infodoanhnghiep.com")
    argument_parser.add_argument("--no-doanhnghiep-biz", action="store_true", help="Không tra doanhnghiep.biz (số điện thoại)")
    argument_parser.add_argument("--no-registry", action="store_true", help="Không tra tratencongty.com (người đại diện pháp luật)")
    argument_parser.add_argument("--no-website", action="store_true", help="Không đọc website công ty")
    argument_parser.add_argument("--output", help="Thư mục kết quả")

    return argument_parser.parse_args()


def build_settings(arguments: argparse.Namespace) -> Settings:
    """
    Gộp config.py với tham số dòng lệnh.
    """
    selected_cities = arguments.cities or config.SELECTED_CITIES
    if list(selected_cities) == ["all"]:
        selected_cities = list(config.ALL_CITIES)

    unknown_cities = [city for city in selected_cities if city not in config.ALL_CITIES]
    if unknown_cities:
        sys.exit(f"Khu vực không có trong config.ALL_CITIES (kiểm tra lại chính tả, có dấu): {unknown_cities}")

    cities = {city: config.ALL_CITIES[city]["keys"] for city in selected_cities}
    infodoanhnghiep_paths = {city: config.ALL_CITIES[city]["infodoanhnghiep"] for city in selected_cities}
    all_cities = {city: city_config["keys"] for city, city_config in config.ALL_CITIES.items()}

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
        infodoanhnghiep_paths=infodoanhnghiep_paths,
        all_cities=all_cities,
        discovery_sources=list(discovery_sources),
        input_file=input_file,
        directory_max_pages_per_city=arguments.directory_pages or config.DIRECTORY_MAX_PAGES_PER_CITY,
        registry_max_pages_per_city=arguments.registry_pages or config.REGISTRY_MAX_PAGES_PER_CITY,
        keywords=arguments.keywords or config.KEYWORDS,
        max_companies=arguments.max_companies or config.MAX_COMPANIES,
        use_vietqr_tax_lookup=(config.USE_VIETQR_TAX_LOOKUP or arguments.vietqr) and not arguments.no_vietqr,
        vietqr_wait_if_rate_limited=config.VIETQR_WAIT_IF_RATE_LIMITED,
        vietqr_free_proxies=config.VIETQR_FREE_PROXIES or arguments.vietqr_free_proxies,
        vietqr_free_proxy_max=config.VIETQR_FREE_PROXY_MAX,
        vietqr_free_proxy_min=config.VIETQR_FREE_PROXY_MIN,
        vietqr_free_proxy_refresh_minutes=config.VIETQR_FREE_PROXY_REFRESH_MINUTES,
        use_infodoanhnghiep=config.USE_INFODOANHNGHIEP and not arguments.no_infodoanhnghiep,
        infodoanhnghiep_delay_seconds=config.INFODOANHNGHIEP_DELAY_SECONDS,
        use_doanhnghiep_biz=config.USE_DOANHNGHIEP_BIZ and not arguments.no_doanhnghiep_biz,
        doanhnghiep_biz_delay_seconds=config.DOANHNGHIEP_BIZ_DELAY_SECONDS,
        use_tratencongty=config.USE_TRATENCONGTY and not arguments.no_registry,
        tratencongty_fetch_detail=config.TRATENCONGTY_FETCH_DETAIL,
        tratencongty_search_by_name=config.TRATENCONGTY_SEARCH_BY_NAME,
        enrich_from_website=config.ENRICH_FROM_WEBSITE and not arguments.no_website,
        vietqr_delay_seconds=config.VIETQR_DELAY_SECONDS,
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
    Khóa thư mục output để không có 2 tiến trình cùng ghi CSV. Trả về None nếu đang bị khóa.
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

    any_backfill_source = settings.use_vietqr_tax_lookup or settings.use_infodoanhnghiep or settings.use_doanhnghiep_biz
    run_backfill = any_backfill_source and (
        arguments.vietqr_backfill or (config.VIETQR_BACKFILL_AFTER_CRAWL and not arguments.no_vietqr_backfill)
    )
    try:
        if not arguments.vietqr_backfill:
            written_count = run_crawl(settings)
            logger.info("Xong giai đoạn 1. Ghi mới %d doanh nghiệp.", written_count)

        if run_backfill:
            run_vietqr_backfill(settings)
        elif arguments.vietqr_backfill:
            logger.warning("VietQR, infodoanhnghiep và doanhnghiep.biz đều đang tắt, không tra bù.")
    except KeyboardInterrupt:
        logger.warning("Đã dừng. Chạy lại để tiếp tục từ chỗ dừng.")

        return 130

    logger.info(
        "Xong. Kết quả: %s và %s",
        settings.output_dir / "companies.csv",
        settings.output_dir / "contacts.csv",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
