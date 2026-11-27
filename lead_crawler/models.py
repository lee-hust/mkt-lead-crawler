"""
Mô hình dữ liệu chung: Company và ContactPerson.
"""

from dataclasses import dataclass, field

# Cột của companies.csv; đổi danh sách thì file cũ tự nâng cấp (storage.upgrade_csv_columns).
# 27/11/2026 bỏ 16 cột luôn trống (Tên thương hiệu, Email, cột website); trường vẫn còn trong Company.
COMPANY_COLUMNS = [
    ("record_id", "Mã bản ghi"),
    ("discovered_by", "Tìm thấy từ"),
    ("company_name", "Tên công ty"),
    ("legal_name", "Tên pháp lý (Cục Thuế)"),
    ("international_name", "Tên tiếng Anh"),
    ("short_name", "Tên viết tắt"),
    ("tax_code", "Mã số thuế"),
    ("tax_code_source", "Nguồn MST"),
    ("tax_status", "Trạng thái MST"),
    ("tax_office", "Cơ quan thuế quản lý"),
    ("legal_representative", "Người đại diện pháp luật"),
    ("contacts_summary", "Liên hệ & chức vụ"),
    ("contact_count", "Số liên hệ"),
    ("legal_form", "Loại hình DN (đăng ký)"),
    ("license_date", "Ngày thành lập / cấp phép"),
    ("founded_year", "Năm thành lập"),
    ("operating_since", "Ngày bắt đầu hoạt động"),
    ("years_active", "Số năm hoạt động"),
    ("employee_count", "Số lao động"),
    ("branch_count", "Số chi nhánh / VP đại diện"),
    ("industry", "Ngành nghề chính"),
    ("industry_guess", "Lĩnh vực (suy từ tên)"),
    ("registered_industries", "Ngành nghề đăng ký (mã VSIC)"),
    ("search_category", "Danh mục quét"),
    ("target_city", "Khu vực quét"),
    ("matched_by", "Khớp khu vực theo"),
    ("city", "Tỉnh/TP"),
    ("district", "Phường/Quận"),
    ("address", "Địa chỉ"),
    ("registered_address", "Địa chỉ đăng ký thuế"),
    ("phone", "Điện thoại"),
    ("directory_url", "Link doanhnghiep.me"),
    ("registry_url", "Link tratencongty"),
    ("infodoanhnghiep_url", "Link infodoanhnghiep"),
    ("doanhnghiep_biz_url", "Link doanhnghiep.biz"),
    ("sources", "Nguồn dữ liệu"),
    ("crawled_at", "Ngày thu thập"),
]

# Thứ tự cột và tên cột tiếng Việt trong contacts.csv
CONTACT_COLUMNS = [
    ("record_id", "Mã bản ghi"),
    ("tax_code", "Mã số thuế"),
    ("company_name", "Tên công ty"),
    ("target_city", "Khu vực quét"),
    ("full_name", "Họ tên"),
    ("position", "Chức vụ / Bộ phận"),
    ("contact_type", "Loại liên hệ"),
    ("phone", "Điện thoại"),
    ("email", "Email"),
    ("source", "Nguồn"),
    ("source_url", "Link nguồn"),
]

CONTACT_TYPE_PERSON = "Cá nhân"

TAX_CODE_SOURCE_WEBSITE = "Website công ty"


@dataclass
class Company:
    """
    Một doanh nghiệp. Nguồn bổ sung chỉ điền trường trống (set_if_empty), trừ dữ liệu thuế.
    """

    record_id: str = ""
    discovered_by: str = ""
    company_name: str = ""
    brand_name: str = ""
    legal_name: str = ""
    international_name: str = ""
    short_name: str = ""
    tax_code: str = ""
    tax_code_source: str = ""
    tax_status: str = ""
    tax_office: str = ""
    legal_representative: str = ""
    contacts_summary: str = ""
    contact_count: str = ""
    legal_form: str = ""
    license_date: str = ""
    founded_year: str = ""
    operating_since: str = ""
    years_active: str = ""
    employee_count: str = ""
    branch_count: str = ""
    industry: str = ""
    industry_guess: str = ""
    registered_industries: str = ""
    search_category: str = ""
    target_city: str = ""
    matched_by: str = ""
    city: str = ""
    district: str = ""
    address: str = ""
    registered_address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    facebook: str = ""
    zalo: str = ""
    linkedin: str = ""
    youtube: str = ""
    tiktok: str = ""
    website_emails: str = ""
    website_phones: str = ""
    website_people: str = ""
    website_title: str = ""
    website_description: str = ""
    website_platform: str = ""
    website_has_english: str = ""
    website_hiring_page: str = ""
    directory_url: str = ""
    registry_url: str = ""
    infodoanhnghiep_url: str = ""
    doanhnghiep_biz_url: str = ""
    sources: list[str] = field(default_factory=list)
    crawled_at: str = ""

    def set_if_empty(
        self,
        attribute_name: str,
        value,
    ) -> None:
        """
        Chỉ gán giá trị khi trường đang trống, để nguồn đến trước được ưu tiên.
        """
        if value and not getattr(self, attribute_name):
            setattr(self, attribute_name, str(value).strip())

    def add_source(self, source_name: str) -> None:
        """
        Ghi nhận nguồn đã đóng góp dữ liệu cho doanh nghiệp này.
        """
        if source_name not in self.sources:
            self.sources.append(source_name)

    def to_csv_row(self) -> list[str]:
        """
        Đổi sang một dòng CSV theo thứ tự COMPANY_COLUMNS.
        """
        row = []
        for attribute_name, _ in COMPANY_COLUMNS:
            value = getattr(self, attribute_name)
            if isinstance(value, list):
                value = "; ".join(value)

            row.append(value or "")

        return row


@dataclass
class ContactPerson:
    """
    Một người liên hệ thuộc một doanh nghiệp, kèm nguồn để MKT kiểm chứng.
    """

    record_id: str = ""
    tax_code: str = ""
    company_name: str = ""
    target_city: str = ""
    full_name: str = ""
    position: str = ""
    contact_type: str = ""
    phone: str = ""
    email: str = ""
    source: str = ""
    source_url: str = ""

    def to_csv_row(self) -> list[str]:
        """
        Đổi sang một dòng CSV theo thứ tự CONTACT_COLUMNS.
        """
        return [getattr(self, attribute_name) or "" for attribute_name, _ in CONTACT_COLUMNS]
