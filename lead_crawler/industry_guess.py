"""
Suy lĩnh vực hoạt động từ tên công ty (và ngành nghề nếu có) bằng từ khóa.
Dùng cho công ty mới đăng ký chưa có ngành nghề trên trang nguồn. Đây là ước đoán,
được ghi vào cột riêng "Lĩnh vực (suy từ tên)" để MKT phân nhóm nhanh.
"""

from lead_crawler.text_utils import to_ascii_key

# Lĩnh vực -> các từ khóa không dấu (so khớp nguyên cụm từ trong tên, tránh "ai" khớp nhầm "hai").
SPECIFIC_INDUSTRIES = {
    "Công nghệ - Phần mềm": [
        "cong-nghe", "phan-mem", "software", "tech", "technology", "technologies", "so-hoa", "ai", "digital",
        "tin-hoc", "vien-thong", "lap-trinh", "it", "data", "du-lieu", "cloud", "solutions", "giai-phap-cong-nghe",
    ],
    "Xây dựng - Kiến trúc - Nội thất": [
        "xay-dung", "kien-truc", "noi-that", "co-dien", "xay-lap", "thi-cong", "vat-lieu-xay-dung", "construction",
    ],
    "Bất động sản": ["bat-dong-san", "dia-oc", "real-estate", "nha-dat"],
    "Vận tải - Logistics": [
        "van-tai", "logistics", "giao-nhan", "chuyen-phat", "kho-van", "van-chuyen", "shipping", "express", "taxi",
    ],
    "Du lịch - Khách sạn": ["du-lich", "travel", "lu-hanh", "khach-san", "hotel", "resort", "homestay", "tour"],
    "Thực phẩm - Đồ uống - Nhà hàng": [
        "thuc-pham", "food", "foods", "nong-san", "do-uong", "nha-hang", "am-thuc", "cafe", "coffee", "tra-sua",
        "tra-chanh", "banh-mi", "banh-ngot", "banh-keo", "bia", "ruou", "nuoc-giai-khat", "beverage",
    ],
    "Dệt may - Thời trang": ["thoi-trang", "may-mac", "det-may", "fashion", "giay-dep", "tui-xach"],
    "Xuất nhập khẩu": ["xuat-nhap-khau", "xnk", "import", "export", "import-export"],
    "Cơ khí - Máy móc - Thiết bị": [
        "co-khi", "che-tao", "may-moc", "thiet-bi", "tu-dong-hoa", "automation", "dien-tu", "dien-lanh", "engineering",
        "ky-thuat", "machinery",
    ],
    "Y tế - Dược - Làm đẹp": [
        "y-te", "duoc-pham", "nha-thuoc", "thuoc-tay", "pharma", "clinic", "phong-kham", "benh-vien", "nha-khoa", "dental", "skin",
        "tham-my", "spa", "my-pham", "cosmetics", "beauty", "medical", "healthcare",
    ],
    "Giáo dục - Đào tạo": [
        "giao-duc", "dao-tao", "education", "academy", "ngoai-ngu", "english", "edu", "hoc-vien", "truong-hoc",
        "mam-non", "mau-giao",
    ],
    "Tài chính - Đầu tư - Kế toán": [
        "tai-chinh", "dau-tu", "chung-khoan", "bao-hiem", "ke-toan", "kiem-toan", "dich-vu-thue", "tu-van-thue",
        "dai-ly-thue", "finance", "capital",
        "invest", "investment", "holdings",
    ],
    "Marketing - Truyền thông - Sự kiện": [
        "quang-cao", "truyen-thong", "marketing", "media", "su-kien", "event", "events", "in-an", "agency", "studio",
    ],
    "Nông nghiệp - Thủy sản": ["nong-nghiep", "chan-nuoi", "thuy-san", "lam-nghiep", "phan-bon", "giong", "agri"],
    "Môi trường - Xử lý nước": ["moi-truong", "environment", "xu-ly-nuoc", "rac-thai", "xu-ly-chat-thai"],
    "Ô tô - Xe máy - Phụ tùng": ["o-to", "xe-may", "phu-tung", "auto", "motor", "xe-dien"],
    "Năng lượng - Điện": ["nang-luong", "dien-mat-troi", "solar", "energy", "power", "dien-luc"],
    "Hóa chất - Nhựa - Bao bì": [
        "hoa-chat", "chemical", "nhua", "bao-bi", "plastic", "packaging", "son-nuoc", "son-tuong", "son-cong-nghiep",
    ],
    "Mẹ và bé - Đồ chơi": ["me-va-be", "baby", "mom", "kids", "do-choi", "toys"],
    "Nhân sự - Việc làm": ["nhan-luc", "tuyen-dung", "viec-lam", "hr", "cung-ung-lao-dong"],
    "Luật - Tư vấn": ["luat", "law", "phap-ly", "tu-van", "consulting", "consultancy"],
    "An ninh - Bảo vệ": ["an-ninh", "bao-ve", "security"],
    "Thương mại điện tử - Bán lẻ": ["thuong-mai-dien-tu", "ecommerce", "e-commerce", "sieu-thi", "mart", "store", "shop"],
    "Gỗ - Nội thất gỗ": ["go", "wood", "lam-san"],
    "Kim loại - Thép": ["thep", "kim-loai", "inox", "nhom", "steel", "metal"],
    "Văn hóa - Nghệ thuật - Giải trí": [
        "van-hoa", "nghe-thuat", "giai-tri", "entertainment", "phim", "film", "am-nhac", "music", "san-khau", "art",
    ],
    "Thể thao - Fitness": ["the-thao", "gym", "fitness", "yoga", "sport", "sports", "golf", "bong-da"],
}

# Chỉ dùng khi không khớp lĩnh vực cụ thể nào.
GENERIC_INDUSTRIES = {
    "Thương mại - Dịch vụ tổng hợp": ["thuong-mai", "dich-vu", "trading", "services", "tong-hop"],
    "Sản xuất": ["san-xuat", "manufacturing"],
}

MAX_INDUSTRIES = 2

# Loại hình doanh nghiệp theo cụm từ trong tên (không dấu), xét theo thứ tự:
# đơn vị phụ thuộc (chi nhánh, VPĐD, địa điểm) trước, vì tên của chúng chứa cả "Công ty TNHH ...".
LEGAL_FORM_PATTERNS = [
    ("chi-nhanh", "Chi nhánh"),
    ("van-phong-dai-dien", "Văn phòng đại diện"),
    ("dia-diem-kinh-doanh", "Địa điểm kinh doanh"),
    ("hop-tac-xa", "Hợp tác xã"),
    ("doanh-nghiep-tu-nhan", "Doanh nghiệp tư nhân"),
    ("cong-ty-hop-danh", "Công ty hợp danh"),
    ("co-phan", "Công ty cổ phần"),
    ("cong-ty-cp", "Công ty cổ phần"),
    ("mot-thanh-vien", "Công ty TNHH một thành viên"),
    ("mtv", "Công ty TNHH một thành viên"),
    ("tnhh", "Công ty TNHH"),
    ("trach-nhiem-huu-han", "Công ty TNHH"),
]


def _matched_industries(
    name_key: str,
    industry_keywords: dict[str, list[str]],
) -> list[str]:
    """
    Các lĩnh vực có từ khóa xuất hiện nguyên cụm trong name_key (đã bao "-" hai đầu).
    """
    return [
        industry
        for industry, keywords in industry_keywords.items()
        if any(f"-{keyword}-" in name_key for keyword in keywords)
    ]


def guess_industry(
    text: str,
    allow_generic: bool = True,
) -> str:
    """
    Trả về tối đa 2 lĩnh vực đoán được, ngăn cách bằng "; " ("" nếu không đoán được).
    allow_generic=False: chỉ nhận lĩnh vực cụ thể, bỏ qua nhóm chung chung (Thương mại, Sản xuất).
    """
    name_key = "-" + to_ascii_key(text) + "-"
    industries = _matched_industries(
        name_key,
        SPECIFIC_INDUSTRIES,
    )
    if not industries and allow_generic:
        industries = _matched_industries(
            name_key,
            GENERIC_INDUSTRIES,
        )

    return "; ".join(industries[:MAX_INDUSTRIES])


def guess_industry_from_texts(texts: list[str]) -> str:
    """
    Đoán từ nhiều nguồn chữ theo thứ tự ưu tiên (vd. tên công ty -> ngành chính -> ngành đăng ký đầu tiên):
    ưu tiên lĩnh vực cụ thể ở bất kỳ nguồn nào; chỉ khi không có mới dùng nhóm chung chung.
    """
    for allow_generic in (False, True):
        for text in texts:
            industry = guess_industry(
                text,
                allow_generic,
            )
            if industry:
                return industry

    return ""


def infer_legal_form(company_name: str) -> str:
    """
    Suy loại hình doanh nghiệp từ tên đăng ký, vd. "Công ty TNHH ..." -> "Công ty TNHH" ("" nếu không rõ).
    """
    name_key = "-" + to_ascii_key(company_name) + "-"
    for phrase, legal_form in LEGAL_FORM_PATTERNS:
        if f"-{phrase}-" in name_key:
            return legal_form

    return ""
