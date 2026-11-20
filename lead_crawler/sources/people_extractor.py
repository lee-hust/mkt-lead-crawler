"""
Nhận diện cặp (họ tên, chức vụ) trong văn bản trang web, ví dụ:
    "Giám đốc: Ông Nguyễn Văn Nam"
    "Bà Trần Thị Hoa - Kế toán trưởng"
    "NGUYỄN VĂN NAM" xuống dòng "Tổng Giám đốc"
Đây là heuristic: kết quả luôn kèm link nguồn để MKT kiểm tra lại.
"""

import re

from lead_crawler.text_utils import clean_text, extract_emails, extract_phones, looks_like_person_name

UPPER = "A-ZÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴ"
LOWER = "a-zàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ"
WORD = f"[{UPPER}][{LOWER}]+"
HONORIFIC = r"(?:Ông|Bà|Anh|Chị|Mr|Mrs|Ms|Miss)\.?"
NAME = rf"(?:{HONORIFIC}\s+{WORD}(?:\s+{WORD}){{0,4}}|{WORD}(?:\s+{WORD}){{1,4}})"

TITLE_PATTERNS = [
    r"Chủ tịch Hội đồng quản trị",
    r"Chủ tịch Hội đồng thành viên",
    r"Phó Chủ tịch HĐQT",
    r"Chủ tịch HĐQT",
    r"Chủ tịch HĐTV",
    r"Phó Chủ tịch",
    r"Chủ tịch",
    r"Phó Tổng Giám đốc",
    r"Tổng Giám đốc",
    r"Giám đốc điều hành",
    r"Giám đốc (?:kinh doanh|tài chính|kỹ thuật|marketing|nhân sự|sản xuất|chi nhánh|dự án|vận hành|thương mại|bán hàng)",
    r"Phó Giám đốc",
    r"Giám đốc",
    r"Kế toán trưởng",
    r"Trưởng phòng(?: [^\W\d_]+){1,3}?",
    r"Trưởng (?:ban|bộ phận|nhóm)",
    r"Người đại diện(?: theo)? pháp luật",
    r"Nhà sáng lập",
    r"Đồng sáng lập",
    r"Co-?Founder",
    r"Founder",
    r"CEO",
    r"CTO",
    r"CFO",
    r"COO",
    r"CMO",
    r"General Director",
    r"Managing Director",
    r"Deputy (?:General )?Director",
    r"Sales Director",
    r"Sales Manager",
    r"Director",
    r"Chairman",
    r"President",
]
TITLE = "(?i:" + "|".join(TITLE_PATTERNS) + ")"

TITLE_THEN_NAME_REGEX = re.compile(rf"(?P<title>{TITLE})\s*[:\-–—]\s*(?P<name>{NAME})")
NAME_THEN_TITLE_REGEX = re.compile(rf"(?P<name>{NAME})\s*[,\-–—|:(]\s*(?P<title>{TITLE})\b")
NAME_ONLY_REGEX = re.compile(rf"{NAME}")
TITLE_AT_START_REGEX = re.compile(rf"(?P<title>{TITLE})\b")

# Từ hay dính vào cuối tên khi trang không có dấu phân cách, ví dụ "Nguyễn Văn Nam Điện thoại: ..."
TRAILING_NOISE_WORDS = {"điện", "email", "hotline", "sđt", "địa", "website", "tel", "mobile", "số", "di", "zalo"}

MAX_LINE_LENGTH = 400


def trim_name(name: str) -> str:
    """
    Bỏ các từ nhiễu dính ở cuối tên.
    """
    words = clean_text(name).split()
    while words and words[-1].lower() in TRAILING_NOISE_WORDS:
        words.pop()

    return " ".join(words)


def extract_people(lines: list[str]) -> list[dict]:
    """
    Trả về [{"name", "title", "phone", "email"}] tìm được trong các dòng văn bản.
    SĐT/email chỉ lấy khi nằm cùng dòng với người đó.
    """
    people: dict[str, dict] = {}

    def add_person(
        raw_name: str,
        raw_title: str,
        line: str,
    ) -> None:
        name = trim_name(raw_name)
        title = clean_text(raw_title)
        if not looks_like_person_name(name):
            return

        key = name.lower()
        if key in people:
            return

        phones = extract_phones(line)
        emails = extract_emails(line)
        people[key] = {
            "name": name,
            "title": title,
            "phone": phones[0] if phones else "",
            "email": emails[0] if emails else "",
        }

    for index, raw_line in enumerate(lines):
        line = clean_text(raw_line)
        if not line or len(line) > MAX_LINE_LENGTH:
            continue

        candidate_line = line.title() if line.isupper() else line

        for match in TITLE_THEN_NAME_REGEX.finditer(candidate_line):
            add_person(
                match.group("name"),
                match.group("title"),
                line,
            )

        for match in NAME_THEN_TITLE_REGEX.finditer(candidate_line):
            add_person(
                match.group("name"),
                match.group("title"),
                line,
            )

        if NAME_ONLY_REGEX.fullmatch(candidate_line) and index + 1 < len(lines):
            next_line = clean_text(lines[index + 1])
            title_match = TITLE_AT_START_REGEX.match(next_line)
            if title_match:
                add_person(
                    candidate_line,
                    title_match.group("title"),
                    line,
                )

    return list(people.values())
