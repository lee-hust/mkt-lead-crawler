"""
Mô hình dữ liệu chung: một doanh nghiệp (Company) và một người liên hệ (ContactPerson).
Mọi nguồn đều ghi vào cùng mô hình này để gộp được với nhau.
"""

from dataclasses import dataclass, field

# Thứ tự cột và tên cột tiếng Việt trong companies.csv
COMPANY_COLUMNS = [
    ("record_id", "Mã bản ghi"),
    ("discovered_by", "Tìm thấy từ"),
    ("company_name", "Tên công ty"),
    ("brand_name", "Tên thương hiệu"),
    ("legal_name", "Tên pháp lý (Cục Thuế)"),
    ("international_name", "Tên tiếng Anh"),
    ("short_name", "Tên viết tắt"),
    ("tax_code", "Mã số thuế"),
    ("tax_code_source", "Nguồn MST"),
    ("tax_status", "Trạng thái MST"),
    ("legal_representative", "Người đại diện pháp luật"),
    ("contacts_summary", "Liên hệ & chức vụ"),
    ("contact_count", "Số liên hệ"),
    ("legal_form", "Loại hình DN (đăng ký)"),
    ("license_date", "Ngày thành lập / cấp phép"),
    ("founded_year", "Năm thành lập"),
    ("operating_since", "Ngày bắt đầu hoạt động"),
    ("years_active", "Số năm hoạt động"),
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
    ("email", "Email"),
    ("website", "Website"),
    ("facebook", "Facebook"),
    ("zalo", "Zalo"),
    ("linkedin", "LinkedIn (trang công ty)"),
    ("youtube", "YouTube"),
    ("tiktok", "TikTok"),
    ("website_emails", "Email (từ website)"),
    ("website_phones", "SĐT (từ website)"),
    ("website_people", "Lãnh đạo/nhân sự (từ website)"),
    ("website_title", "Tiêu đề website"),
    ("website_description", "Mô tả website"),
    ("website_platform", "Nền tảng website"),
    ("website_has_english", "Có bản tiếng Anh"),
    ("website_hiring_page", "Trang tuyển dụng"),
    ("directory_url", "Link doanhnghiep.me"),
    ("registry_url", "Link tratencongty"),
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
    Một doanh nghiệp. Các nguồn bổ sung chỉ điền vào trường còn trống (set_if_empty),
    trừ nguồn chính thức như Cục Thuế được phép ghi đè trường pháp lý.
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
    legal_representative: str = ""
    contacts_summary: str = ""
    contact_count: str = ""
    legal_form: str = ""
    license_date: str = ""
    founded_year: str = ""
    operating_since: str = ""
    years_active: str = ""
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
