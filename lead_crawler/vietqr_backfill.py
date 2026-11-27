"""
Giai đoạn 2: tra VietQR bù cho các công ty trong companies.csv chưa có dữ liệu VietQR.

Giai đoạn 1 (cào) chạy ở chế độ không chờ: VietQR còn lượt thì tra, hết lượt thì bỏ qua cho nhanh.
Giai đoạn này đọc lại companies.csv, chỉ tra những công ty có MST mà chưa có "VietQR (Cục Thuế)" trong
cột "Nguồn dữ liệu", chờ VietQR theo đúng thời gian API yêu cầu, rồi cập nhật thẳng vào file.
File được ghi lại định kỳ, nên dừng giữa chừng không mất phần đã tra; chạy lại sẽ tra tiếp phần còn thiếu.
"""

import csv
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from lead_crawler.http_client import HttpClient
from lead_crawler.models import COMPANY_COLUMNS, CONTACT_COLUMNS, Company
from lead_crawler.pipeline import Settings, build_http_client, fill_derived_fields
from lead_crawler.sources.vietqr import API_HOST, VietQrSource
from lead_crawler.storage import CSV_ENCODING

logger = logging.getLogger(__name__)

# Ghi lại file khoảng 10 phút một lần, hoặc sớm hơn khi đã cập nhật bấy nhiêu công ty chưa lưu.
SAVE_INTERVAL_SECONDS = 600
SAVE_MAX_UNSAVED = 500
# Thời gian mỗi lượt tra của một IP, dùng để ước tính thời gian còn lại. Từ 27/11/2026 Cloudflare trước VietQR
# chỉ cho mỗi IP khoảng 1 lượt / phút (trước đó ~25 lượt / 10 phút); có proxy thì chia cho số đường gọi.
SECONDS_PER_LOOKUP = 60
# Dù nhiều proxy, mỗi lượt vẫn mất ít nhất bấy nhiêu giây (tra lần lượt từng công ty).
MIN_SECONDS_PER_LOOKUP = 1.5
# In tiến độ (tốc độ thực tế, thời gian còn lại, giờ dự kiến xong) bấy nhiêu giây một lần.
PROGRESS_LOG_SECONDS = 300
# Tốc độ thực tế tính trung bình trong bấy nhiêu giây gần nhất (số proxy thay đổi liên tục).
RATE_WINDOW_SECONDS = 15 * 60
# Cần đo được ít nhất bấy nhiêu giây và bấy nhiêu lượt mới dùng tốc độ thực tế; chưa đủ thì ước tính theo số đường.
MIN_MEASURE_SECONDS = 120
MIN_MEASURE_LOOKUPS = 3


class BackfillProgress:
    """
    Đo tốc độ tra bù thực tế (trung bình trong RATE_WINDOW_SECONDS gần nhất) để ước tính thời gian còn lại.
    """

    def __init__(self, total_count: int):
        self.total_count = total_count
        self.samples: deque[tuple[float, int]] = deque([(time.monotonic(), 0)])

    def record(self, done_count: int) -> None:
        """
        Ghi nhận đã tra xong done_count công ty; bỏ các mốc cũ hơn cửa sổ đo.
        """
        now = time.monotonic()
        self.samples.append((now, done_count))
        while len(self.samples) > 2 and now - self.samples[1][0] >= RATE_WINDOW_SECONDS:
            self.samples.popleft()

    def measured_seconds_per_lookup(self) -> Optional[float]:
        """
        Số giây trung bình mỗi lượt tra theo đo thực tế; None nếu chưa đo đủ lâu.
        """
        first_time, first_count = self.samples[0]
        last_time, last_count = self.samples[-1]
        measured_lookups = last_count - first_count
        measured_seconds = last_time - first_time
        if measured_lookups < MIN_MEASURE_LOOKUPS or measured_seconds < MIN_MEASURE_SECONDS:
            return None

        return measured_seconds / measured_lookups

    def describe(
        self,
        done_count: int,
        http_client: HttpClient,
    ) -> str:
        """
        Mô tả tiến độ: đã tra bao nhiêu, tốc độ, thời gian còn lại và giờ dự kiến xong.
        """
        seconds_per_lookup = self.measured_seconds_per_lookup()
        speed_source = "đo thực tế 15 phút gần nhất"
        if seconds_per_lookup is None:
            seconds_per_lookup = estimate_seconds_per_lookup(http_client)
            speed_source = "ước tính theo số đường gọi, chưa đủ số liệu đo"

        remaining_count = self.total_count - done_count
        remaining_seconds = remaining_count * seconds_per_lookup
        finish_at = datetime.now() + timedelta(seconds=remaining_seconds)

        return (
            f"đã tra {done_count}/{self.total_count} ({done_count * 100 // max(self.total_count, 1)}%), "
            f"tốc độ ~{3600 / seconds_per_lookup:.0f} công ty/giờ ({speed_source}), "
            f"đang tra qua {http_client.count_proxy_routes(API_HOST)} proxy + IP máy; "
            f"còn {remaining_count} công ty, khoảng {format_duration(remaining_seconds)}, "
            f"xong khoảng {finish_at:%H:%M} ngày {finish_at:%d/%m}"
        )


def run_vietqr_backfill(settings: Settings) -> int:
    """
    Tra bù VietQR cho companies.csv trong settings.output_dir. Trả về số công ty đã bổ sung được dữ liệu.
    """
    companies_path = settings.output_dir / "companies.csv"
    if not companies_path.exists():
        logger.info("Giai đoạn 2: chưa có %s, không có gì để tra bù", companies_path)

        return 0

    company_headers = [header for _, header in COMPANY_COLUMNS]
    headers, rows = read_csv_rows(companies_path)
    if headers != company_headers:
        logger.warning("Giai đoạn 2: cột của %s khác phiên bản hiện tại, bỏ qua tra bù", companies_path.name)

        return 0

    companies = [company_from_row(row) for row in rows]
    pending_companies = [company for company in companies if needs_vietqr(company)]
    if not pending_companies:
        logger.info("=== Giai đoạn 2: cả %d công ty đều không cần tra bù VietQR", len(companies))

        return 0

    http_client = build_http_client(settings)
    vietqr_source = VietQrSource(
        http_client,
        settings.vietqr_delay_seconds,
        True,
        True,
    )
    logger.info(
        "=== Giai đoạn 2: tra bù VietQR cho %d / %d công ty (ước tính ban đầu %s theo số đường gọi hiện có; "
        "tiến độ và giờ dự kiến xong theo tốc độ thực tế được in %d phút một lần)",
        len(pending_companies),
        len(companies),
        format_duration(len(pending_companies) * estimate_seconds_per_lookup(http_client)),
        PROGRESS_LOG_SECONDS // 60,
    )

    backfill_progress = BackfillProgress(len(pending_companies))
    changed_tax_codes: dict[str, str] = {}
    updated_count = 0
    not_found_count = 0
    unsaved_count = 0
    last_save_time = time.monotonic()
    last_progress_time = time.monotonic()
    try:
        for index, company in enumerate(pending_companies, start=1):
            if http_client.is_blocked(API_HOST):
                logger.error("Giai đoạn 2: VietQR từ chối truy cập, dừng tra bù. Chạy lại sau để tra tiếp.")
                break

            old_tax_code = company.tax_code
            vietqr_source.enrich(company)
            if company.tax_code != old_tax_code:
                changed_tax_codes[company.record_id] = company.tax_code
                unsaved_count += 1
                logger.info(
                    "  [VietQR bù %d/%d] %s | MST %s (lấy từ website) là của công ty khác, đã bỏ",
                    index,
                    len(pending_companies),
                    company.company_name,
                    old_tax_code,
                )
            elif VietQrSource.name in company.sources:
                fill_derived_fields(company)
                updated_count += 1
                unsaved_count += 1
                logger.info(
                    "  [VietQR bù %d/%d] %s | MST %s | %s",
                    index,
                    len(pending_companies),
                    company.company_name,
                    company.tax_code,
                    company.tax_status or "-",
                )
            else:
                not_found_count += 1
                logger.info(
                    "  [VietQR bù %d/%d] %s | MST %s | VietQR không có dữ liệu",
                    index,
                    len(pending_companies),
                    company.company_name,
                    old_tax_code,
                )

            backfill_progress.record(index)
            if time.monotonic() - last_progress_time >= PROGRESS_LOG_SECONDS:
                last_progress_time = time.monotonic()
                logger.info(
                    "Giai đoạn 2 - tiến độ: %s",
                    backfill_progress.describe(
                        index,
                        http_client,
                    ),
                )

            is_save_due = time.monotonic() - last_save_time >= SAVE_INTERVAL_SECONDS
            if unsaved_count and (is_save_due or unsaved_count >= SAVE_MAX_UNSAVED):
                last_save_time = time.monotonic()
                if save_companies(companies_path, company_headers, companies):
                    unsaved_count = 0
                    logger.info("Giai đoạn 2: đã lưu vào %s", companies_path.name)
    finally:
        if unsaved_count:
            save_companies(companies_path, company_headers, companies)

        if changed_tax_codes:
            update_contact_tax_codes(settings.output_dir / "contacts.csv", changed_tax_codes)

    logger.info(
        "Xong giai đoạn 2: bổ sung VietQR cho %d công ty, %d công ty VietQR không có dữ liệu",
        updated_count,
        not_found_count,
    )

    return updated_count


def estimate_seconds_per_lookup(http_client: HttpClient) -> float:
    """
    Thời gian trung bình mỗi lượt tra: mỗi đường gọi (IP máy chạy tool, từng proxy) được ~1 lượt / SECONDS_PER_LOOKUP.
    """
    route_count = max(len(http_client.get_routes(API_HOST)), 1)

    return max(SECONDS_PER_LOOKUP / route_count, MIN_SECONDS_PER_LOOKUP)


def needs_vietqr(company: Company) -> bool:
    """
    Công ty có MST mà chưa được tra VietQR thành công.
    """
    return bool(company.tax_code) and VietQrSource.name not in company.sources


def company_from_row(row: list[str]) -> Company:
    """
    Dựng lại Company từ một dòng companies.csv (cùng thứ tự cột COMPANY_COLUMNS).
    """
    company = Company()
    for index, (attribute_name, _) in enumerate(COMPANY_COLUMNS):
        value = row[index] if index < len(row) else ""
        if attribute_name == "sources":
            company.sources = [source_name.strip() for source_name in value.split(";") if source_name.strip()]
        else:
            setattr(company, attribute_name, value)

    return company


def save_companies(
    companies_path: Path,
    company_headers: list[str],
    companies: list[Company],
) -> bool:
    """
    Ghi lại toàn bộ companies.csv.
    """

    return write_csv_rows(
        companies_path,
        company_headers,
        [company.to_csv_row() for company in companies],
    )


def update_contact_tax_codes(
    contacts_path: Path,
    changed_tax_codes: dict[str, str],
) -> None:
    """
    Sửa cột MST trong contacts.csv cho các công ty mà VietQR đã bỏ MST sai (MST lấy nhầm từ website).
    """
    if not contacts_path.exists():
        return

    contact_headers = [header for _, header in CONTACT_COLUMNS]
    headers, rows = read_csv_rows(contacts_path)
    if headers != contact_headers:
        return

    attribute_names = [attribute_name for attribute_name, _ in CONTACT_COLUMNS]
    record_index = attribute_names.index("record_id")
    tax_index = attribute_names.index("tax_code")
    for row in rows:
        if len(row) > max(record_index, tax_index) and row[record_index] in changed_tax_codes:
            row[tax_index] = changed_tax_codes[row[record_index]]

    write_csv_rows(
        contacts_path,
        contact_headers,
        rows,
    )


def read_csv_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    """
    Đọc dòng tiêu đề và các dòng dữ liệu của file CSV.
    """
    with path.open("r", encoding=CSV_ENCODING, newline="") as csv_file:
        csv_reader = csv.reader(csv_file)
        headers = next(csv_reader, [])
        rows = [row for row in csv_reader if row]

    return headers, rows


def write_csv_rows(
    path: Path,
    headers: list[str],
    rows: list[list[str]],
) -> bool:
    """
    Ghi ra file tạm rồi thay file cũ, để lỗi giữa chừng không làm hỏng file đang có.
    Trả về False nếu không ghi được (vd. file đang mở bằng Excel trên Windows).
    """
    temporary_path = path.with_name(path.name + ".tmp")
    try:
        with temporary_path.open("w", encoding=CSV_ENCODING, newline="") as csv_file:
            csv_writer = csv.writer(csv_file)
            csv_writer.writerow(headers)
            csv_writer.writerows(rows)

        os.replace(temporary_path, path)
    except OSError as os_error:
        logger.error("Không ghi được %s (%s). Nếu đang mở file bằng Excel thì đóng lại.", path.name, os_error)

        return False

    return True


def format_duration(total_seconds: float) -> str:
    """
    Đổi số giây sang dạng dễ đọc, vd. "3 giờ 20 phút".
    """
    total_minutes = int(total_seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours} giờ {minutes} phút"

    return f"{minutes} phút"
