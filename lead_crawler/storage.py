"""
Ghi kết quả ra CSV và gộp trùng; chạy lại sẽ bỏ qua công ty đã có nên tiếp tục được khi bị dừng.
"""

import csv
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from lead_crawler.models import COMPANY_COLUMNS, CONTACT_COLUMNS, Company, ContactPerson
from lead_crawler.text_utils import company_name_tokens, to_ascii_key

logger = logging.getLogger(__name__)

# utf-8-sig thêm BOM để Excel mở CSV tiếng Việt không lỗi font
CSV_ENCODING = "utf-8-sig"


def upgrade_csv_columns(
    path: Path,
    headers: list[str],
) -> bool:
    """
    File CSV cũ khác bộ cột (cùng cột đầu tiên): ghi lại theo bộ cột mới, ghép theo tên cột, có bản sao lưu.
    Trả về True nếu file khớp bộ cột mới.
    """
    if not path.exists() or path.stat().st_size == 0:
        return True

    with path.open("r", encoding=CSV_ENCODING, newline="") as existing_file:
        csv_reader = csv.reader(existing_file)
        existing_headers = next(csv_reader, [])
        if existing_headers == headers:
            return True

        is_same_kind = bool(existing_headers) and existing_headers[0] == headers[0]
        if not is_same_kind or len(set(existing_headers)) != len(existing_headers):
            return False

        rows = [row for row in csv_reader if row]

    positions = [existing_headers.index(header) if header in existing_headers else -1 for header in headers]
    added_headers = [header for header in headers if header not in existing_headers]
    removed_headers = [header for header in existing_headers if header not in headers]
    dropped_value_count = sum(
        1
        for row in rows
        for index, header in enumerate(existing_headers)
        if header in removed_headers and index < len(row) and row[index].strip()
    )
    backup_path = path.with_name(f"{path.stem}_truoc_nang_cap_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
    temporary_path = path.with_name(path.name + ".tmp")
    try:
        shutil.copy2(path, backup_path)
        with temporary_path.open("w", encoding=CSV_ENCODING, newline="") as upgraded_file:
            csv_writer = csv.writer(upgraded_file)
            csv_writer.writerow(headers)
            for row in rows:
                csv_writer.writerow([row[position] if 0 <= position < len(row) else "" for position in positions])

        os.replace(temporary_path, path)
    except OSError as os_error:
        logger.error("Không nâng cấp được cột của %s (%s). Nếu đang mở file bằng Excel thì đóng lại.", path.name, os_error)

        return False

    logger.warning(
        "Đã nâng cấp cột của %s (%d dòng, giữ nguyên dữ liệu): thêm %s; bỏ %s (%d ô có dữ liệu). Bản gốc: %s",
        path.name,
        len(rows),
        ", ".join(added_headers) or "không",
        ", ".join(removed_headers) or "không",
        dropped_value_count,
        backup_path.name,
    )

    return True


def company_name_key(
    company_name: str,
    city: str,
) -> str:
    """
    Khóa gộp trùng theo tên công ty (đã bỏ phần loại hình) + khu vực; "" nếu tên rỗng.
    """
    tokens = company_name_tokens(company_name)
    if not tokens:
        return ""

    return "-".join(sorted(tokens)) + "|" + to_ascii_key(city)


class CsvStore:
    """
    Ghi nối tiếp companies.csv (và contacts.csv nếu bật) từng công ty, gộp trùng theo mã bản ghi, MST, tên + khu vực.
    """

    def __init__(
        self,
        output_dir: Path,
        write_contacts_file: bool = False,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        self.seen_record_ids: set[str] = set()
        self.seen_tax_codes: set[str] = set()
        self.seen_name_keys: set[str] = set()
        company_headers = [header for _, header in COMPANY_COLUMNS]
        self.companies_file, self.companies_writer = self._open(
            output_dir / "companies.csv",
            company_headers,
            True,
        )
        self.contacts_file = None
        self.contacts_writer = None
        if write_contacts_file:
            contact_headers = [header for _, header in CONTACT_COLUMNS]
            self.contacts_file, self.contacts_writer = self._open(
                output_dir / "contacts.csv",
                contact_headers,
                False,
            )

    def is_known(self, company: Company) -> bool:
        """
        Công ty đã được ghi trước đó chưa (theo mã bản ghi, MST hoặc tên + khu vực).
        """
        if company.record_id and company.record_id in self.seen_record_ids:
            return True

        if self.is_known_tax_code(company.tax_code):
            return True

        name_keys = {
            company_name_key(name, company.target_city)
            for name in (company.legal_name, company.company_name)
            if name
        }

        return any(key and key in self.seen_name_keys for key in name_keys)

    def is_known_tax_code(self, tax_code: str) -> bool:
        """
        MST đã được ghi trước đó chưa.
        """
        return bool(tax_code) and tax_code in self.seen_tax_codes

    def remember(self, company: Company) -> None:
        """
        Đánh dấu đã xử lý (kể cả khi bỏ qua) để không xử lý lại trong lần chạy này.
        """
        if company.record_id:
            self.seen_record_ids.add(company.record_id)

        if company.tax_code:
            self.seen_tax_codes.add(company.tax_code)

        for name in (company.legal_name, company.company_name):
            name_key = company_name_key(name, company.target_city)
            if name_key:
                self.seen_name_keys.add(name_key)

    def write(
        self,
        company: Company,
        contact_persons: list[ContactPerson],
    ) -> None:
        """
        Ghi một công ty (người liên hệ đã gộp vào cột Liên hệ & chức vụ) và contacts.csv nếu bật.
        """
        self.companies_writer.writerow(company.to_csv_row())
        self.companies_file.flush()
        if self.contacts_writer is not None:
            for contact_person in contact_persons:
                self.contacts_writer.writerow(contact_person.to_csv_row())

            self.contacts_file.flush()

        self.remember(company)

    def close(self) -> None:
        """
        Đóng file.
        """
        self.companies_file.close()
        if self.contacts_file is not None:
            self.contacts_file.close()

    def _open(
        self,
        path: Path,
        headers: list[str],
        load_seen: bool,
    ):
        """
        Mở file để ghi nối tiếp; khác bộ cột thì nâng cấp, không được thì đổi tên file cũ.
        """
        upgrade_csv_columns(
            path,
            headers,
        )
        if path.exists() and path.stat().st_size > 0:
            with path.open("r", encoding=CSV_ENCODING, newline="") as existing_file:
                csv_reader = csv.reader(existing_file)
                existing_headers = next(csv_reader, [])
                if load_seen:
                    self._load_seen(
                        csv_reader,
                        existing_headers,
                    )

            if existing_headers != headers:
                backup_path = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
                path.rename(backup_path)
                logger.warning("Cột của %s đã thay đổi, file cũ được đổi tên thành %s", path.name, backup_path.name)

        is_new_file = not path.exists() or path.stat().st_size == 0
        output_file = path.open("a", encoding=CSV_ENCODING, newline="")
        csv_writer = csv.writer(output_file)
        if is_new_file:
            csv_writer.writerow(headers)
            output_file.flush()

        return output_file, csv_writer

    def _load_seen(
        self,
        csv_reader,
        headers: list[str],
    ) -> None:
        """
        Nạp mã bản ghi, MST, tên + khu vực đã có trong file cũ.
        """
        column_names = dict(COMPANY_COLUMNS)

        def column_index(attribute_name: str) -> int:
            header = column_names[attribute_name]

            return headers.index(header) if header in headers else -1

        def cell(
            row: list[str],
            index: int,
        ) -> str:
            return row[index] if 0 <= index < len(row) else ""

        record_index = column_index("record_id")
        tax_index = column_index("tax_code")
        legal_name_index = column_index("legal_name")
        name_index = column_index("company_name")
        city_index = column_index("target_city")
        row_count = 0
        for row in csv_reader:
            row_count += 1
            if cell(row, record_index):
                self.seen_record_ids.add(cell(row, record_index))

            if cell(row, tax_index):
                self.seen_tax_codes.add(cell(row, tax_index))

            for name in (cell(row, legal_name_index), cell(row, name_index)):
                name_key = company_name_key(name, cell(row, city_index))
                if name_key:
                    self.seen_name_keys.add(name_key)

        logger.info("Đã có sẵn %d công ty trong file cũ, sẽ bỏ qua khi gặp lại", row_count)
