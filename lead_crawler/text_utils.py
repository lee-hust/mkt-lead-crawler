"""
Các hàm xử lý chuỗi dùng chung cho mọi nguồn dữ liệu.
"""

import re
import unicodedata

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
PHONE_CANDIDATE_REGEX = re.compile(r"(?:\(\+84\)|\+84|84|0)[\s.\-]?\d(?:[\s.\-]?\d){7,10}")
IGNORED_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
IGNORED_EMAIL_DOMAINS = (
    "example.com",
    "domain.com",
    "yourdomain.com",
    "email.com",
    "sentry.io",
    "wixpress.com",
)
HONORIFIC_REGEX = re.compile(r"^(?:ông|bà|anh|chị|mr|mrs|ms|miss)\.?\s+", re.IGNORECASE)

# Họ phổ biến của người Việt (dạng không dấu) để lọc tên người, tránh nhận nhầm tên công ty.
VIETNAMESE_SURNAMES = {
    "nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo", "dang",
    "bui", "do", "ho", "ngo", "duong", "ly", "dao", "doan", "vuong", "trinh",
    "truong", "lam", "phung", "mai", "to", "ha", "ta", "luu", "cao", "dinh",
    "quach", "luong", "kieu", "thai", "tu", "chau", "hua", "nghiem", "au", "trieu",
    "khong", "dam", "tang", "than", "la", "giang", "chu", "mac", "luc", "bach",
    "ton", "ninh", "kim", "lai", "hau", "diep", "vien", "quan", "ong", "phuong",
    "dong", "han", "khuc", "thach", "nong", "cu", "lo", "manh", "tong", "lac",
    "uong", "ung", "giap", "an", "banh", "chung", "tieu", "dieu", "hong", "son",
}

# Từ (có dấu, chữ thường) cho thấy chuỗi là tên bộ phận/công ty chứ không phải tên người.
NON_PERSON_WORDS = {
    "công", "ty", "tnhh", "cổ", "phần", "phòng", "ban", "giám", "đốc", "tổng",
    "chủ", "tịch", "trưởng", "hotline", "kinh", "doanh", "kỹ", "thuật", "dịch", "vụ",
    "sản", "xuất", "thương", "mại", "company", "group", "technology", "sales", "support",
    "cskh", "tư", "vấn", "bộ", "phận", "chăm", "sóc", "khách", "hàng", "đài",
    "điện", "thoại", "email", "website", "địa", "chỉ", "số", "fax", "tel", "mobile",
}

LEGAL_NAME_MARKERS = (
    "công ty",
    "cty",
    "tập đoàn",
    "doanh nghiệp",
    "hợp tác xã",
    "chi nhánh",
    "văn phòng đại diện",
    "hộ kinh doanh",
    "xí nghiệp",
    "nhà máy",
    "trung tâm",
    "cửa hàng",
)


def strip_accents(text: str) -> str:
    """
    Bỏ dấu tiếng Việt, ví dụ "Hà Nội" thành "Ha Noi".
    """
    if not text:
        return ""

    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)

    return "".join(character for character in normalized if unicodedata.category(character) != "Mn")


def to_ascii_key(text: str) -> str:
    """
    Đổi chuỗi về dạng dùng để so khớp: không dấu, chữ thường, nối bằng dấu "-".
    """
    ascii_text = strip_accents(text or "").lower()

    return re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")


def contains_city_key(
    text: str,
    city_keys: list[str],
) -> bool:
    """
    Chuỗi có chứa trọn cụm từ khóa khu vực không ("an-giang" không khớp "Tân Giang").
    """
    location_key = f"-{to_ascii_key(text)}-"

    return any(f"-{city_key}-" in location_key for city_key in city_keys)


def find_city_in_text(
    text: str,
    cities: dict[str, list[str]],
) -> str:
    """
    Khu vực nhắc tới trong chuỗi (lấy tên xuất hiện sau cùng); không thấy thì "".
    """
    location_key = f"-{to_ascii_key(text)}-"
    found_city = ""
    found_position = -1
    for city_name, city_keys in cities.items():
        for city_key in city_keys:
            position = location_key.rfind(f"-{city_key}-")
            if position > found_position:
                found_city = city_name
                found_position = position

    return found_city


def clean_text(text) -> str:
    """
    Gộp khoảng trắng thừa và bỏ khoảng trắng ở hai đầu.
    """
    if not text:
        return ""

    cleaned = re.sub(r"\s+", " ", str(text)).strip()

    return re.sub(r"\s+([,.;:])", r"\1", cleaned)


def unique_keep_order(values) -> list:
    """
    Bỏ phần tử trùng và phần tử rỗng, giữ nguyên thứ tự xuất hiện.
    """
    seen = set()
    result = []
    for value in values:
        if not value or value in seen:
            continue

        seen.add(value)
        result.append(value)

    return result


def normalize_phone(raw: str) -> str:
    """
    Chuẩn hóa số điện thoại Việt Nam về dạng 0xxxxxxxxx; trả về "" nếu không hợp lệ.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("84") and len(digits) in (11, 12):
        digits = "0" + digits[2:]

    if not is_valid_vietnamese_phone(digits):
        return ""

    return digits


def is_valid_vietnamese_phone(digits: str) -> bool:
    """
    Di động: 10 số, đầu 03/05/07/08/09. Cố định: 11 số, đầu 02. Tổng đài: 1800/1900.
    """
    if re.fullmatch(r"0[35789]\d{8}", digits):
        return True

    if re.fullmatch(r"02\d{9}", digits):
        return True

    return bool(re.fullmatch(r"(?:1800|1900)\d{4,6}", digits))


def extract_phones(text: str) -> list[str]:
    """
    Tìm các số điện thoại hợp lệ trong một đoạn văn bản.
    """
    phones = [normalize_phone(match.group(0)) for match in PHONE_CANDIDATE_REGEX.finditer(text or "")]

    return unique_keep_order(phones)


def extract_emails(text: str) -> list[str]:
    """
    Tìm email trong văn bản, bỏ các chuỗi trông như tên file ảnh hoặc email mẫu.
    """
    emails = []
    for match in EMAIL_REGEX.finditer(text or ""):
        email = match.group(0).strip(".").lower()
        if email.endswith(IGNORED_EMAIL_SUFFIXES):
            continue

        if email.split("@", 1)[1] in IGNORED_EMAIL_DOMAINS:
            continue

        emails.append(email)

    return unique_keep_order(emails)


def split_brand_and_legal_name(listing_name: str) -> tuple[str, str]:
    """
    Tách "Thương hiệu - Công Ty TNHH ABC" thành ("Thương hiệu", "Công Ty TNHH ABC").
    """
    name = clean_text(listing_name)
    if " - " not in name:
        return "", name

    brand_name, legal_name = name.split(" - ", 1)
    if legal_name.lower().startswith(LEGAL_NAME_MARKERS):
        return brand_name.strip(), legal_name.strip()

    return "", name


def looks_like_person_name(name: str) -> bool:
    """
    Đoán chuỗi có phải tên người: có danh xưng hoặc bắt đầu bằng họ Việt, 2-5 từ viết hoa đầu.
    """
    name = clean_text(name)
    if not name:
        return False

    has_honorific = bool(HONORIFIC_REGEX.match(name))
    bare_name = HONORIFIC_REGEX.sub("", name).strip()
    words = bare_name.split()
    min_words = 1 if has_honorific else 2
    if not min_words <= len(words) <= 5:
        return False

    if any(not word[0].isupper() for word in words):
        return False

    if any(word.lower() in NON_PERSON_WORDS for word in words):
        return False

    if has_honorific:
        return True

    return to_ascii_key(words[0]) in VIETNAMESE_SURNAMES


# Cụm chỉ loại hình doanh nghiệp (dạng không dấu), bỏ đi trước khi so tên hai công ty.
LEGAL_FORM_PHRASES = (
    "cong-ty-trach-nhiem-huu-han",
    "trach-nhiem-huu-han",
    "mot-thanh-vien",
    "hai-thanh-vien-tro-len",
    "cong-ty-co-phan",
    "cong-ty-cp",
    "cong-ty",
    "cty",
    "tnhh",
    "co-phan",
    "mtv",
    "doanh-nghiep-tu-nhan",
    "hop-tac-xa",
    "tap-doan",
    "chi-nhanh",
    "co-ltd",
    "ltd",
    "jsc",
    "company",
    "limited",
)


def company_name_tokens(company_name: str) -> set[str]:
    """
    Tách tên công ty thành tập từ đặc trưng, đã bỏ phần loại hình (Công ty TNHH, CP, MTV...).
    """
    name_key = "-" + to_ascii_key(company_name) + "-"
    for phrase in LEGAL_FORM_PHRASES:
        name_key = name_key.replace("-" + phrase + "-", "-")

    return {token for token in name_key.split("-") if token}


def is_same_company_name(
    first_name: str,
    second_name: str,
) -> bool:
    """
    Cùng một công ty không: ít nhất 80% từ đặc trưng của tên ngắn hơn có trong tên kia.
    """
    first_tokens = company_name_tokens(first_name)
    second_tokens = company_name_tokens(second_name)
    if not first_tokens or not second_tokens:
        return False

    overlap = len(first_tokens & second_tokens) / min(len(first_tokens), len(second_tokens))

    return overlap >= 0.8
