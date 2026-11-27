"""
Website công ty: đọc trang chủ và trang liên hệ / giới thiệu để lấy email, SĐT, lãnh đạo, MST, mạng xã hội.
Không giải mã email bị ẩn, không đoán email theo tên người.
"""

import logging
import re
from urllib.parse import urljoin, urlparse

from lead_crawler.html_soup import make_soup

from lead_crawler.http_client import HttpClient
from lead_crawler.models import CONTACT_TYPE_PERSON, TAX_CODE_SOURCE_WEBSITE, Company, ContactPerson
from lead_crawler.sources.base import EnrichmentSource
from lead_crawler.sources.people_extractor import extract_people
from lead_crawler.text_utils import (
    clean_text,
    extract_emails,
    extract_phones,
    normalize_phone,
    to_ascii_key,
    unique_keep_order,
)

logger = logging.getLogger(__name__)

SKIPPED_DOMAINS = (
    "facebook.com",
    "fb.com",
    "zalo.me",
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
    "linkedin.com",
    "shopee.vn",
    "lazada.vn",
    "tiki.vn",
    "sendo.vn",
    "google.com",
    "goo.gl",
    "trangvangvietnam.com",
    "yellowpages.vn",
)
# Tên miền email miễn phí / nhà mạng: không suy ra website từ các tên miền này.
FREE_EMAIL_DOMAINS = (
    "gmail.com",
    "gmail.com.vn",
    "googlemail.com",
    "yahoo.com",
    "yahoo.com.vn",
    "ymail.com",
    "hotmail.com",
    "outlook.com",
    "outlook.com.vn",
    "live.com",
    "msn.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "zoho.com",
    "qq.com",
    "163.com",
    "126.com",
    "vnn.vn",
    "fpt.vn",
    "viettel.vn",
)
SKIPPED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".zip", ".rar", ".doc", ".docx", ".xls", ".xlsx", ".mp4")

# Từ khóa trong link (dạng không dấu) và điểm ưu tiên: trang lãnh đạo > liên hệ > giới thiệu.
PAGE_KEYWORDS = {
    "ban-lanh-dao": 3,
    "lanh-dao": 3,
    "ban-giam-doc": 3,
    "ban-dieu-hanh": 3,
    "doi-ngu": 3,
    "nhan-su": 3,
    "so-do-to-chuc": 3,
    "co-cau-to-chuc": 3,
    "leadership": 3,
    "our-team": 3,
    "management": 3,
    "team": 2,
    "lien-he": 2,
    "lienhe": 2,
    "contact": 2,
    "gioi-thieu": 1,
    "gioithieu": 1,
    "ve-chung-toi": 1,
    "about": 1,
}
HIRING_KEYWORDS = ("tuyen-dung", "tuyendung", "career", "careers", "recruitment", "jobs", "co-hoi-nghe-nghiep")
ENGLISH_KEYWORDS = ("english", "/en/", "/en", "lang=en", "hl=en", "tieng-anh")

# Dòng chứa SĐT: so theo từ nguyên vẹn (tránh "tel" khớp "hotel") hoặc theo cụm nhiều từ.
PHONE_LINE_WORDS = {"hotline", "tel", "phone", "sdt", "dt", "mobile", "zalo", "fax"}
PHONE_LINE_PHRASES = ("dien-thoai", "di-dong", "lien-he")

# Cụm "MST: ...": đọc MST rồi xóa khỏi dòng trước khi tìm SĐT (MST giống số di động).
TAX_CODE_MENTION_REGEX = re.compile(
    r"(?i)(?:mst|mã số thuế|mã số doanh nghiệp|msdn|mã số dn|mã doanh nghiệp|tax code|tax id)"
    r"\s*[:.]?\s*(\d[\d\s.]{8,12}\d(?:\s*-\s*\d{3})?)"
)

SOCIAL_PATTERNS = {
    "facebook": re.compile(r"^https?://(?:www\.|m\.)?(?:facebook|fb)\.com/(?!sharer|share|plugins|dialog|tr\b)[^?#]+", re.I),
    "linkedin": re.compile(r"^https?://(?:[a-z]{2,3}\.)?linkedin\.com/company/[^?#]+", re.I),
    "youtube": re.compile(r"^https?://(?:www\.)?youtube\.com/(?:channel/|c/|user/|@)[^?#]+", re.I),
    "tiktok": re.compile(r"^https?://(?:www\.)?tiktok\.com/@[^?#]+", re.I),
    "zalo": re.compile(r"^https?://(?:www\.)?zalo\.me/[^?#]+", re.I),
}
PLATFORM_SIGNATURES = (
    ("WordPress", ("wp-content", "wp-includes")),
    ("Haravan", ("haravan",)),
    ("Sapo", ("sapo.vn", "bizweb")),
    ("Shopify", ("cdn.shopify.com",)),
    ("Wix", ("wixstatic.com", "wix.com")),
    ("Joomla", ("/media/jui/", "joomla")),
    ("Webflow", ("webflow",)),
    ("Ladipage", ("ladipage", "ladicdn")),
    ("Squarespace", ("squarespace",)),
    ("Magento", ("mage/", "magento")),
    ("Next.js", ("/_next/",)),
)

MAX_EMAILS = 20
MAX_PHONES = 20


class CompanyWebsiteSource(EnrichmentSource):
    """
    Bổ sung thông tin công ty tự công bố trên website.
    """

    name = "Website công ty"

    def __init__(
        self,
        http_client: HttpClient,
        delay_seconds: float,
        max_pages: int,
    ):
        self.http_client = http_client
        self.delay_seconds = delay_seconds
        self.max_pages = max_pages

    def enrich(self, company: Company) -> list[ContactPerson]:
        """
        Đọc trang chủ + tối đa max_pages trang liên quan của website công ty.
        """
        website_url = normalize_website(company.website)
        is_guessed_from_email = False
        if not website_url:
            website_url = website_from_email(company.email)
            is_guessed_from_email = bool(website_url)

        if not website_url:
            return []

        host = urlparse(website_url).netloc.lower()
        self.http_client.set_host_delay(
            host,
            self.delay_seconds,
        )
        home_html = self.http_client.get_text(website_url)
        if home_html is None:
            return []

        if is_guessed_from_email:
            company.set_if_empty("website", website_url)

        apply_home_page_signals(
            company,
            home_html,
        )
        home_links = find_internal_links(
            website_url,
            home_html,
        )
        company.set_if_empty("website_hiring_page", find_hiring_page(home_links))
        pages = [(website_url, home_html)]
        for page_url in rank_related_pages(home_links)[: self.max_pages]:
            page_html = self.http_client.get_text(page_url)
            if page_html is not None:
                pages.append((page_url, page_html))

        emails: list[str] = []
        phones: list[str] = []
        contact_persons: list[ContactPerson] = []
        seen_names: set[str] = set()
        for page_url, page_html in pages:
            page_contacts = extract_page_contacts(page_html)
            emails.extend(page_contacts["emails"])
            phones.extend(page_contacts["phones"])
            if not company.tax_code and page_contacts["tax_codes"]:
                company.tax_code = page_contacts["tax_codes"][0]
                company.tax_code_source = TAX_CODE_SOURCE_WEBSITE

            for social_name, social_url in page_contacts["social_links"].items():
                company.set_if_empty(social_name, social_url)

            for person in page_contacts["people"]:
                if person["name"].lower() in seen_names:
                    continue

                seen_names.add(person["name"].lower())
                contact_persons.append(
                    ContactPerson(
                        full_name=person["name"],
                        position=person["title"],
                        contact_type=CONTACT_TYPE_PERSON,
                        phone=person["phone"],
                        email=person["email"],
                        source=self.name,
                        source_url=page_url,
                    )
                )

        tax_code_digits = re.sub(r"\D", "", company.tax_code)
        phones = [phone for phone in unique_keep_order(phones) if phone != tax_code_digits]
        company.website_emails = "; ".join(unique_keep_order(emails)[:MAX_EMAILS])
        company.website_phones = "; ".join(phones[:MAX_PHONES])
        company.website_people = "; ".join(
            f"{contact.position}: {contact.full_name}" for contact in contact_persons
        )
        company.add_source(self.name)

        return contact_persons


def normalize_website(website: str) -> str:
    """
    Chuẩn hóa link website; trả về "" nếu là mạng xã hội / sàn TMĐT.
    """
    website = (website or "").strip()
    if not website:
        return ""

    if not website.startswith(("http://", "https://")):
        website = "http://" + website

    host = urlparse(website).netloc.lower()
    if not host or any(host == domain or host.endswith("." + domain) for domain in SKIPPED_DOMAINS):
        return ""

    return website


def website_from_email(email: str) -> str:
    """
    info@abc.com.vn -> http://abc.com.vn (bỏ qua email miễn phí như gmail, yahoo...).
    """
    if not email or "@" not in email:
        return ""

    domain = email.split("@", 1)[1].strip().lower()
    if any(domain == free_domain or domain.endswith("." + free_domain) for free_domain in FREE_EMAIL_DOMAINS):
        return ""

    return normalize_website(domain)


def same_site(
    first_host: str,
    second_host: str,
) -> bool:
    """
    So sánh hai host, bỏ qua tiền tố "www.".
    """
    return first_host.lower().removeprefix("www.") == second_host.lower().removeprefix("www.")


def find_internal_links(
    website_url: str,
    home_html: str,
) -> list[tuple[str, str]]:
    """
    Lấy các link nội bộ trên trang chủ: [(url, khóa không dấu của url + chữ trên link)].
    """
    beautiful_soup = make_soup(home_html)
    home_host = urlparse(website_url).netloc
    links: dict[str, str] = {}
    for anchor in beautiful_soup.select("a[href]"):
        href = anchor["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue

        page_url = urljoin(website_url, href).split("#")[0]
        parsed_url = urlparse(page_url)
        if parsed_url.scheme not in ("http", "https") or not same_site(parsed_url.netloc, home_host):
            continue

        if parsed_url.path.lower().endswith(SKIPPED_EXTENSIONS):
            continue

        link_key = to_ascii_key(parsed_url.path + " " + anchor.get_text(" "))
        links[page_url] = (links.get(page_url, "") + "-" + link_key).strip("-")

    return list(links.items())


def rank_related_pages(links: list[tuple[str, str]]) -> list[str]:
    """
    Chọn link tới trang liên hệ / giới thiệu / lãnh đạo, xếp theo độ ưu tiên.
    """
    scored_urls: dict[str, int] = {}
    for page_url, link_key in links:
        score = max((weight for keyword, weight in PAGE_KEYWORDS.items() if keyword in link_key), default=0)
        if score:
            scored_urls[page_url] = score

    return sorted(scored_urls, key=lambda url: -scored_urls[url])


def find_hiring_page(links: list[tuple[str, str]]) -> str:
    """
    Link trang tuyển dụng (dấu hiệu công ty đang mở rộng), "" nếu không có.
    """
    for page_url, link_key in links:
        if any(keyword in link_key for keyword in HIRING_KEYWORDS):
            return page_url

    return ""


def apply_home_page_signals(
    company: Company,
    home_html: str,
) -> None:
    """
    Đọc tiêu đề, mô tả, nền tảng web và có bản tiếng Anh hay không từ trang chủ.
    """
    beautiful_soup = make_soup(home_html)
    title_tag = beautiful_soup.find("title")
    if title_tag is not None:
        company.set_if_empty("website_title", clean_text(title_tag.get_text())[:200])

    for selector in ('meta[name="description"]', 'meta[property="og:description"]'):
        meta_tag = beautiful_soup.select_one(selector)
        if meta_tag is not None and meta_tag.get("content"):
            company.set_if_empty("website_description", clean_text(meta_tag["content"])[:400])
            break

    lowered_html = home_html.lower()
    platforms = [name for name, signatures in PLATFORM_SIGNATURES if any(sign in lowered_html for sign in signatures)]
    company.set_if_empty("website_platform", ", ".join(platforms[:2]))

    has_english = any(
        alternate_tag.get("hreflang", "").lower().startswith("en")
        for alternate_tag in beautiful_soup.select("link[hreflang]")
    )
    if not has_english:
        for anchor in beautiful_soup.select("a[href]"):
            anchor_key = anchor["href"].lower() + " " + clean_text(anchor.get_text()).lower()
            if any(keyword in anchor_key for keyword in ENGLISH_KEYWORDS) or clean_text(anchor.get_text()) == "EN":
                has_english = True
                break

    company.set_if_empty("website_has_english", "Có" if has_english else "Không")


def extract_page_contacts(html: str) -> dict:
    """
    Lấy email, SĐT, người, MST, mạng xã hội từ một trang; SĐT chỉ lấy từ tel: hoặc dòng có chữ điện thoại / hotline.
    """
    beautiful_soup = make_soup(html)
    social_links: dict[str, str] = {}
    for anchor in beautiful_soup.select("a[href]"):
        href = anchor["href"].strip()
        for social_name, pattern in SOCIAL_PATTERNS.items():
            match = pattern.match(href)
            if match and social_name not in social_links:
                social_links[social_name] = match.group(0).rstrip("/")

    for tag in beautiful_soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    emails = [
        anchor["href"][7:].split("?")[0].strip().lower()
        for anchor in beautiful_soup.select('a[href^="mailto:"]')
    ]
    phones = [normalize_phone(anchor["href"][4:]) for anchor in beautiful_soup.select('a[href^="tel:"]')]

    text = beautiful_soup.get_text("\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    emails.extend(extract_emails(text))

    tax_codes = []
    for match in TAX_CODE_MENTION_REGEX.finditer(clean_text(text)):
        digits = re.sub(r"[^\d\-]", "", match.group(1))
        if re.fullmatch(r"\d{10}(?:-\d{3})?", digits):
            tax_codes.append(digits)

    for line in lines:
        line_key = to_ascii_key(line)
        line_words = set(line_key.split("-"))
        if line_words & PHONE_LINE_WORDS or any(phrase in line_key for phrase in PHONE_LINE_PHRASES):
            phones.extend(extract_phones(TAX_CODE_MENTION_REGEX.sub(" ", line)))

    return {
        "emails": [email for email in unique_keep_order(emails) if extract_emails(email)],
        "phones": unique_keep_order(phones),
        "people": extract_people(lines),
        "tax_codes": unique_keep_order(tax_codes),
        "social_links": social_links,
    }
