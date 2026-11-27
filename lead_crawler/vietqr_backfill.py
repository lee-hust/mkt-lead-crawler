"""
Giai đoạn 2: tra bù companies.csv, lưu định kỳ. Thiếu dữ liệu thuế: infodoanhnghiep trước, VietQR sau; thiếu SĐT:
doanhnghiep.biz.
Log mỗi công ty giữ dạng "[VietQR bù i/N]" để lệnh xem tiến độ cũ vẫn dùng được.
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
from lead_crawler.sources.doanhnghiep_biz import DoanhNghiepBizSource
from lead_crawler.sources.infodoanhnghiep import InfoDoanhNghiepSource
from lead_crawler.sources.vietqr import API_HOST, VietQrSource
from lead_crawler.storage import CSV_ENCODING, upgrade_csv_columns
from lead_crawler.text_utils import find_city_in_text

logger = logging.getLogger(__name__)

# Ghi lại file khoảng 10 phút một lần, hoặc sớm hơn khi đã cập nhật bấy nhiêu công ty chưa lưu.
SAVE_INTERVAL_SECONDS = 600
SAVE_MAX_UNSAVED = 500
# Giây mỗi lượt của một IP với VietQR (Cloudflare ~1 lượt / phút từ 27/11/2026).
SECONDS_PER_LOOKUP = 60
# Dù nhiều proxy, mỗi lượt vẫn mất ít nhất bấy nhiêu giây (tra lần lượt từng công ty).
MIN_SECONDS_PER_LOOKUP = 1.5
# Thời gian tải trang của infodoanhnghiep (ngoài khoảng nghỉ), dùng cho ước tính ban đầu.
INFO_REQUEST_SECONDS = 0.3
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
        estimated_seconds_per_lookup: float,
    ) -> str:
        """
        Mô tả tiến độ: đã tra bao nhiêu, tốc độ, thời gian còn lại và giờ dự kiến xong.
        """
        seconds_per_lookup = self.measured_seconds_per_lookup()
        speed_source = "đo thực tế 15 phút gần nhất"
        if seconds_per_lookup is None:
            seconds_per_lookup = estimated_seconds_per_lookup
            speed_source = "ước tính, chưa đủ số liệu đo"

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
    Tra bù companies.csv cho công ty thiếu dữ liệu thuế hoặc số điện thoại (không tra lại chỉ để lấy số lao động).
    Trả về số công ty bổ sung được.
    """
    companies_path = settings.output_dir / "companies.csv"
    if not companies_path.exists():
        logger.info("Giai đoạn 2: chưa có %s, không có gì để tra bù", companies_path)

        return 0

    company_headers = [header for _, header in COMPANY_COLUMNS]
    if not upgrade_csv_columns(companies_path, company_headers):
        logger.warning("Giai đoạn 2: cột của %s khác phiên bản hiện tại, bỏ qua tra bù", companies_path.name)

        return 0

    _, rows = read_csv_rows(companies_path)
    companies = [company_from_row(row) for row in rows]
    renamed_count = rename_old_provinces(
        companies,
        settings.all_cities,
    )
    if renamed_count:
        save_companies(companies_path, company_headers, companies)
        logger.info("Giai đoạn 2: đổi tên tỉnh cũ sang tỉnh/TP mới (sau sáp nhập) cho %d công ty", renamed_count)
    use_infodoanhnghiep = settings.use_infodoanhnghiep
    use_doanhnghiep_biz = settings.use_doanhnghiep_biz
    pending_companies = [
        company
        for company in companies
        if needs_tax_data(company) or (use_doanhnghiep_biz and needs_phone(company))
    ]
    missing_tax_data_count = sum(1 for company in pending_companies if needs_tax_data(company))
    missing_phone_count = sum(1 for company in pending_companies if use_doanhnghiep_biz and needs_phone(company))
    if not pending_companies:
        logger.info("=== Giai đoạn 2: cả %d công ty đều không cần tra bù", len(companies))

        return 0

    http_client = build_http_client(settings)
    vietqr_source = None
    if settings.use_vietqr_tax_lookup:
        vietqr_source = VietQrSource(
            http_client,
            settings.vietqr_delay_seconds,
            True,
            True,
        )

    info_doanh_nghiep_source = None
    if use_infodoanhnghiep:
        info_doanh_nghiep_source = InfoDoanhNghiepSource(
            http_client,
            settings.infodoanhnghiep_delay_seconds,
            True,
            True,
        )

    doanh_nghiep_biz_source = None
    if use_doanhnghiep_biz:
        doanh_nghiep_biz_source = DoanhNghiepBizSource(
            http_client,
            settings.doanhnghiep_biz_delay_seconds,
            True,
        )

    seconds_per_lookup = estimate_seconds_per_lookup(
        http_client,
        settings,
    )
    logger.info(
        "=== Giai đoạn 2: tra bù cho %d / %d công ty (%d thiếu dữ liệu thuế, %d thiếu số điện thoại); nguồn: %s; "
        "ước tính ban đầu %s, tiến độ theo tốc độ thực tế được in %d phút một lần",
        len(pending_companies),
        len(companies),
        missing_tax_data_count,
        missing_phone_count,
        ", ".join(
            source.name for source in (info_doanh_nghiep_source, vietqr_source, doanh_nghiep_biz_source) if source
        ),
        format_duration(len(pending_companies) * seconds_per_lookup),
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
            vietqr_usable = vietqr_source is not None and not http_client.is_blocked(API_HOST)
            info_usable = info_doanh_nghiep_source is not None and not info_doanh_nghiep_source.is_blocked()
            biz_usable = doanh_nghiep_biz_source is not None and not doanh_nghiep_biz_source.is_blocked()
            if not vietqr_usable and not info_usable and not biz_usable:
                logger.error("Giai đoạn 2: mọi nguồn đều từ chối truy cập, dừng tra bù. Chạy lại sau.")
                break

            old_tax_code = company.tax_code
            old_sources = list(company.sources)
            if info_usable and needs_tax_data(company):
                info_doanh_nghiep_source.enrich(company)

            if vietqr_usable and company.tax_code == old_tax_code and needs_tax_data(company):
                vietqr_source.enrich(company)

            if biz_usable and company.tax_code == old_tax_code and needs_phone(company):
                doanh_nghiep_biz_source.enrich(company)

            new_sources = [source_name for source_name in company.sources if source_name not in old_sources]
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
            elif new_sources:
                fill_derived_fields(company)
                updated_count += 1
                unsaved_count += 1
                logger.info(
                    "  [VietQR bù %d/%d] %s | MST %s | %s | SĐT: %s | lao động: %s | nguồn: %s",
                    index,
                    len(pending_companies),
                    company.company_name,
                    company.tax_code,
                    company.tax_status or "-",
                    company.phone or "-",
                    company.employee_count or "-",
                    ", ".join(new_sources),
                )
            else:
                not_found_count += 1
                logger.info(
                    "  [VietQR bù %d/%d] %s | MST %s | không có dữ liệu",
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
                        seconds_per_lookup,
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
        "Xong giai đoạn 2: bổ sung dữ liệu cho %d công ty, %d công ty không tìm thấy ở nguồn nào",
        updated_count,
        not_found_count,
    )

    return updated_count


def estimate_seconds_per_lookup(
    http_client: HttpClient,
    settings: Settings,
) -> float:
    """
    Ước tính ban đầu số giây mỗi công ty, trước khi đo được tốc độ thực tế.
    """
    seconds = 0.0
    if settings.use_infodoanhnghiep:
        seconds += 2 * settings.infodoanhnghiep_delay_seconds + INFO_REQUEST_SECONDS

    if settings.use_doanhnghiep_biz:
        seconds += 2 * settings.doanhnghiep_biz_delay_seconds + INFO_REQUEST_SECONDS

    if seconds:
        return seconds

    route_count = max(len(http_client.get_routes(API_HOST)), 1)

    return max(SECONDS_PER_LOOKUP / route_count, MIN_SECONDS_PER_LOOKUP)


def needs_tax_data(company: Company) -> bool:
    """
    Công ty có MST mà chưa có dữ liệu đăng ký thuế (chưa tra được VietQR lẫn infodoanhnghiep).
    """
    return (
        bool(company.tax_code)
        and VietQrSource.name not in company.sources
        and InfoDoanhNghiepSource.name not in company.sources
    )


def rename_old_provinces(
    companies: list[Company],
    all_cities: dict[str, list[str]],
) -> int:
    """
    Đổi tên tỉnh cũ (vd. Bình Dương) ở cột Khu vực quét và Tỉnh/TP sang tỉnh/TP mới chứa nó (TP. Hồ Chí Minh).
    Trả về số công ty được đổi.
    """
    renamed_count = 0
    for company in companies:
        is_renamed = False
        for attribute_name in ("target_city", "city"):
            old_name = getattr(company, attribute_name)
            new_name = find_city_in_text(old_name, all_cities) if old_name else ""
            if new_name and new_name != old_name:
                setattr(company, attribute_name, new_name)
                is_renamed = True

        renamed_count += is_renamed

    return renamed_count


def needs_phone(company: Company) -> bool:
    """
    Công ty có MST mà chưa có số điện thoại và chưa tra doanhnghiep.biz.
    """
    return bool(company.tax_code) and not company.phone and DoanhNghiepBizSource.name not in company.sources


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
    Ghi file tạm rồi thay file cũ; False nếu không ghi được (vd. đang mở bằng Excel).
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
