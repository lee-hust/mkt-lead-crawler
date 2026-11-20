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
from pathlib import Path

from lead_crawler.models import COMPANY_COLUMNS, CONTACT_COLUMNS, Company
from lead_crawler.pipeline import Settings, build_http_client, fill_derived_fields
from lead_crawler.sources.vietqr import API_HOST, VietQrSource
from lead_crawler.storage import CSV_ENCODING

logger = logging.getLogger(__name__)

# Ghi lại file sau mỗi bấy nhiêu công ty được cập nhật (~10 phút với giới hạn ~25 lượt / 10 phút của VietQR).
SAVE_EVERY_UPDATES = 25
# Thời gian trung bình mỗi lượt tra khi bị giới hạn ~25 lượt / 10 phút, dùng để ước tính thời gian còn lại.
SECONDS_PER_LOOKUP = 24


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
    logger.info(
        "=== Giai đoạn 2: tra bù VietQR cho %d / %d công ty (ước tính %s)",
        len(pending_companies),
        len(companies),
        format_duration(len(pending_companies) * SECONDS_PER_LOOKUP),
    )
    if not pending_companies:
        return 0

    http_client = build_http_client(settings)
    vietqr_source = VietQrSource(
        http_client,
        settings.vietqr_delay_seconds,
        True,
        True,
    )
    changed_tax_codes: dict[str, str] = {}
    updated_count = 0
    not_found_count = 0
    unsaved_count = 0
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

            if unsaved_count >= SAVE_EVERY_UPDATES:
                if save_companies(companies_path, company_headers, companies):
                    unsaved_count = 0
                    logger.info(
                        "Giai đoạn 2: đã lưu vào %s (còn %d công ty, ước tính %s)",
                        companies_path.name,
                        len(pending_companies) - index,
                        format_duration((len(pending_companies) - index) * SECONDS_PER_LOOKUP),
                    )
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
