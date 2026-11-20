"""
Nguồn file đầu vào: MKT tự đưa danh sách công ty (từ CRM, sự kiện, danh sách mua có bản quyền...),
tool sẽ làm giàu dữ liệu bằng các nguồn bổ sung (MST, người đại diện, website...).

Mẫu file: input_template.csv. Chỉ cần có ít nhất cột "Tên công ty" hoặc "Mã số thuế".
"""

import csv
import io
import logging
import unicodedata
from datetime import date
from pathlib import Path
from typing import Iterator

from lead_crawler.models import Company
from lead_crawler.text_utils import clean_text, find_city_in_text, split_brand_and_legal_name, to_ascii_key

logger = logging.getLogger(__name__)

SOURCE_NAME = "File đầu vào"
TAX_CODE_SOURCE_INPUT = "File đầu vào"

# Tên cột chấp nhận được (so dạng không dấu) -> thuộc tính của Company
INPUT_COLUMNS = {
    "ten-cong-ty": "company_name",
    "company-name": "company_name",
    "ma-so-thue": "tax_code",
    "mst": "tax_code",
    "tax-code": "tax_code",
    "website": "website",
    "email": "email",
    "dien-thoai": "phone",
    "dia-chi": "address",
    "tinh-tp": "city",
    "tinh-thanh-pho": "city",
    "khu-vuc": "city",
    "nganh": "industry",
}


def read_input_companies(
    input_path: Path,
    cities: dict[str, list[str]],
) -> Iterator[Company]:
    """
    Đọc file CSV đầu vào (UTF-8, có hoặc không có BOM) và trả về từng Company.
    Cột Tỉnh/TP dùng để gán khu vực; để trống thì đoán theo địa chỉ.
    """
    if not input_path.exists():
        logger.error("Không tìm thấy file đầu vào: %s", input_path)

        return

    raw_bytes = input_path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel "CSV (Comma delimited)" lưu theo bảng mã Windows; khuyên dùng "CSV UTF-8".
        logger.warning("File đầu vào không phải UTF-8, đọc theo bảng mã Windows (cp1258). Nên lưu dạng 'CSV UTF-8'.")
        text = raw_bytes.decode("cp1258", errors="replace")

    # cp1258 lưu dấu tiếng Việt dạng tổ hợp; chuẩn hóa về dạng dựng sẵn để so khớp đúng.
    text = unicodedata.normalize("NFC", text)
    csv_reader = csv.DictReader(io.StringIO(text, newline=""))
    for row_number, row in enumerate(csv_reader, start=2):
        company = Company(
            discovered_by=SOURCE_NAME,
            sources=[SOURCE_NAME],
            crawled_at=date.today().isoformat(),
        )
        for header, value in row.items():
            attribute_name = INPUT_COLUMNS.get(to_ascii_key(header or ""))
            if attribute_name and value:
                setattr(company, attribute_name, clean_text(value))

        if not company.company_name and not company.tax_code:
            logger.warning("Dòng %d trong file đầu vào thiếu cả tên và MST, bỏ qua", row_number)
            continue

        company.brand_name, company.legal_name = split_brand_and_legal_name(company.company_name)
        if company.tax_code:
            company.tax_code_source = TAX_CODE_SOURCE_INPUT

        company.target_city = guess_city(
            company,
            cities,
        )
        company.matched_by = SOURCE_NAME
        company.record_id = "input:" + (company.tax_code or to_ascii_key(company.company_name))

        yield company


def guess_city(
    company: Company,
    cities: dict[str, list[str]],
) -> str:
    """
    Gán khu vực theo cột Tỉnh/TP hoặc địa chỉ; không xác định được thì để nguyên giá trị đã nhập.
    """
    found_city = find_city_in_text(company.city, cities) or find_city_in_text(company.address, cities)

    return found_city or company.city
