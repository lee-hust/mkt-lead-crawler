"""
Nguồn doanhnghiep.me: cơ sở dữ liệu doanh nghiệp theo tỉnh/thành (Hà Nội ~446 nghìn,
TP.HCM ~833 nghìn, Đà Nẵng ~87 nghìn doanh nghiệp), công ty mới thành lập xếp trước.

- Tìm công ty (iter_companies): phân trang của site bị lỗi (trang 2, 3... luôn hiện lại trang 1),
  nên tool đi theo địa bàn: trang tỉnh -> quận/huyện cũ + phường/xã mới -> phường/xã thuộc quận.
  Mỗi trang địa bàn cho 20 công ty mới nhất của địa bàn đó, có sẵn dạng chữ: tên, MST, điện thoại,
  địa chỉ, ngành nghề chính, ngày thành lập, phường/quận. Hà Nội có khoảng 580 trang địa bàn.
- Bổ sung (enrich): trang chi tiết có người đại diện, tên viết tắt, ngành nghề đăng ký kèm mã.

robots.txt cho phép mọi bot; điều khoản chỉ yêu cầu ghi rõ nguồn doanhnghiep.me
(cột "Nguồn dữ liệu" và "Link doanhnghiep.me" trong CSV đáp ứng yêu cầu này).
"""

import logging
import re
from collections import deque
from datetime import date
from typing import Iterator, Optional

from lead_crawler.html_soup import make_soup
from lead_crawler.http_client import HttpClient
from lead_crawler.models import CONTACT_TYPE_PERSON, Company, ContactPerson
from lead_crawler.sources.base import EnrichmentSource
from lead_crawler.text_utils import clean_text, normalize_phone, to_ascii_key, unique_keep_order

logger = logging.getLogger(__name__)

HOST = "doanhnghiep.me"
BASE_URL = "https://doanhnghiep.me"
SOURCE_NAME = "doanhnghiep.me"
TAX_CODE_SOURCE_DOANHNGHIEP_ME = "doanhnghiep.me"
LEGAL_REPRESENTATIVE_POSITION = "Người đại diện pháp luật"
MAX_INDUSTRIES = 100

# Từ khóa khu vực (config.CITIES) -> đường dẫn tỉnh/thành trên doanhnghiep.me
PROVINCE_SLUGS = {
    "ha-noi": "ha-noi",
    "ho-chi-minh": "ho-chi-minh",
    "da-nang": "da-nang",
    "hai-phong": "hai-phong",
    "can-tho": "can-tho",
}
NO_INFORMATION = "chua-co-thong-tin"


class DoanhNghiepMeSource(EnrichmentSource):
    """
    Tìm công ty theo tỉnh và bổ sung người đại diện / ngành nghề đăng ký từ doanhnghiep.me.
    """

    name = SOURCE_NAME

    def __init__(
        self,
        http_client: HttpClient,
        delay_seconds: float,
        fetch_detail: bool,
    ):
        self.http_client = http_client
        self.fetch_detail = fetch_detail
        http_client.set_host_delay(
            HOST,
            delay_seconds,
        )

    def is_blocked(self) -> bool:
        """
        Site đã từ chối truy cập trong lần chạy này chưa.
        """
        return self.http_client.is_blocked(HOST)

    # ------------------------------------------------------------------ tìm công ty

    def iter_companies(
        self,
        cities: dict[str, list[str]],
        max_pages: Optional[int],
    ) -> Iterator[Company]:
        """
        Duyệt các trang địa bàn của từng tỉnh/thành theo chiều rộng (tỉnh -> quận/phường -> phường con),
        tối đa max_pages trang mỗi tỉnh (None = đi hết). Công ty trùng giữa các trang chỉ trả về một lần.
        """
        for city_name, city_keys in cities.items():
            province_slug = next((slug for key, slug in PROVINCE_SLUGS.items() if key in city_keys), None)
            if province_slug is None:
                logger.warning("%s: chưa có đường dẫn danh sách cho %s", self.name, city_name)
                continue

            location_queue = deque([f"/{province_slug}"])
            visited_locations = set(location_queue)
            seen_record_ids: set[str] = set()
            pages_read = 0
            while location_queue and (max_pages is None or pages_read < max_pages):
                location_path = location_queue.popleft()
                page_html = self.http_client.get_text(
                    BASE_URL + location_path,
                    wait_if_rate_limited=True,
                )
                pages_read += 1
                if page_html is None:
                    if self.is_blocked():
                        return

                    continue

                for link in find_location_links(page_html, province_slug):
                    if link not in visited_locations:
                        visited_locations.add(link)
                        location_queue.append(link)

                companies = [
                    company
                    for company in parse_listing_page(page_html, city_name)
                    if company.record_id not in seen_record_ids
                ]
                seen_record_ids.update(company.record_id for company in companies)
                logger.info(
                    "[%s] %s %s (trang địa bàn %d, còn %d trong hàng đợi): %d công ty mới",
                    self.name,
                    city_name,
                    location_path,
                    pages_read,
                    len(location_queue),
                    len(companies),
                )
                yield from companies

    # ------------------------------------------------------------------ bổ sung

    def enrich(self, company: Company) -> list[ContactPerson]:
        """
        Đọc trang chi tiết doanhnghiep.me (chỉ với công ty tìm thấy từ nguồn này) để lấy người đại diện.
        """
        if not self.fetch_detail or not company.directory_url or self.is_blocked():
            return []

        detail_html = self.http_client.get_text(company.directory_url)
        if detail_html is None:
            return []

        apply_detail_page(
            company,
            detail_html,
        )
        if not company.legal_representative:
            return []

        return [
            ContactPerson(
                full_name=company.legal_representative,
                position=LEGAL_REPRESENTATIVE_POSITION,
                contact_type=CONTACT_TYPE_PERSON,
                source=self.name,
                source_url=company.directory_url,
            )
        ]


def find_location_links(
    page_html: str,
    province_slug: str,
) -> list[str]:
    """
    Link địa bàn trong cùng tỉnh: /<tỉnh>/<quận hoặc phường mới> và /<tỉnh>/<quận>/<phường>.
    Bỏ link phân trang (/pageN, site bị lỗi) và link công ty (từ 3 cấp trở lên).
    """
    links = re.findall(rf'href="(/{re.escape(province_slug)}(?:/[a-z0-9-]+){{1,2}})"', page_html)

    return unique_keep_order(link for link in links if not re.search(r"/page\d+$", link))


def clean_industry(industry_text: str) -> str:
    """
    "Bán buôn ... (Wholesale ...)" -> "Bán buôn ..."; "Chưa có thông tin" -> "".
    """
    industry_text = clean_text(industry_text)
    if to_ascii_key(industry_text).startswith(NO_INFORMATION):
        return ""

    return re.sub(r"\s*\([^()]*\)\s*$", "", industry_text).strip()


def labeled_value(
    container,
    label_prefix: str,
) -> str:
    """
    Tìm thẻ <b>Nhãn:</b> rồi lấy chữ của thẻ <p> ngay sau nó.
    """
    for bold_tag in container.find_all("b"):
        if to_ascii_key(bold_tag.get_text()).startswith(label_prefix):
            value_tag = bold_tag.find_next_sibling("p")
            if value_tag is not None:
                return clean_text(value_tag.get_text(" "))

    return ""


def parse_listing_page(
    page_html: str,
    city_name: str,
) -> list[Company]:
    """
    Đọc các thẻ <article> trên trang danh sách.
    """
    beautiful_soup = make_soup(page_html)
    companies = []
    for article in beautiful_soup.select("article"):
        name_anchor = article.find("a", href=True)
        if name_anchor is None or name_anchor.find("strong") is None:
            continue

        directory_url = BASE_URL + name_anchor["href"] if name_anchor["href"].startswith("/") else name_anchor["href"]
        tax_code = re.sub(r"[^\d\-]", "", labeled_value(article, "ma-so-thue"))
        company_name = clean_text(name_anchor.get_text())
        address_tag = article.find("address")
        address = clean_text(address_tag.get_text(" ")) if address_tag else ""
        address = re.sub(r"^Địa chỉ:\s*", "", address)
        location_tag = article.select_one("p.name-dn")
        founded_tag = article.select_one("p.ngaytl-dn b")
        founded_date = re.sub(r"\s*-\s*", "/", clean_text(founded_tag.get_text())) if founded_tag else ""
        founded_parts = founded_date.split("/")
        if len(founded_parts) == 3:
            founded_date = f"{int(founded_parts[0]):02d}/{int(founded_parts[1]):02d}/{founded_parts[2]}"

        company = Company(
            record_id=f"dnme:{tax_code or to_ascii_key(company_name)}",
            discovered_by=SOURCE_NAME,
            company_name=company_name,
            legal_name=company_name,
            tax_code=tax_code,
            tax_code_source=TAX_CODE_SOURCE_DOANHNGHIEP_ME if tax_code else "",
            phone=normalize_phone(labeled_value(article, "dien-thoai")),
            address=address,
            registered_address=address,
            industry=clean_industry(labeled_value(article, "nganh-nghe-chinh")),
            district=clean_text(location_tag.get_text(" ")) if location_tag else "",
            license_date=founded_date,
            founded_year=founded_parts[-1] if len(founded_parts) == 3 else "",
            city=city_name,
            target_city=city_name,
            matched_by="Địa chỉ đăng ký",
            search_category=f"Danh sách doanh nghiệp theo tỉnh ({SOURCE_NAME})",
            directory_url=directory_url,
            sources=[SOURCE_NAME],
            crawled_at=date.today().isoformat(),
        )
        companies.append(company)

    return companies


def apply_detail_page(
    company: Company,
    detail_html: str,
) -> None:
    """
    Đọc bảng thông tin (MST, điện thoại, tên viết tắt, người đại diện) và ngành nghề đăng ký.
    """
    beautiful_soup = make_soup(detail_html)
    for row in beautiful_soup.select("table.info-msdn tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        label_key = to_ascii_key(cells[0].get_text(" "))
        value = clean_text(cells[1].get_text(" "))
        if not value:
            continue

        if label_key.startswith("nguoi-dai-dien"):
            company.set_if_empty("legal_representative", value)
        elif label_key.startswith("ten-v-tat"):
            company.set_if_empty("short_name", value)
        elif label_key.startswith("dien-thoai"):
            phones = unique_keep_order(normalize_phone(part) for part in re.split(r"[;,/]| - ", value))
            company.set_if_empty("phone", phones[0] if phones else "")
        elif label_key.startswith("ma-so-thue"):
            company.set_if_empty("tax_code", re.sub(r"[^\d\-]", "", value))

    industries = []
    for item in beautiful_soup.select("div.nganhnghe-kd li"):
        industry_anchor = item.find("a")
        code_tag = item.find("b")
        industry_name = clean_industry(industry_anchor.get_text(" ")) if industry_anchor else ""
        industry_code = clean_text(code_tag.get_text()) if code_tag else ""
        if industry_name:
            industries.append(f"{industry_code} {industry_name}".strip() if industry_code not in ("", "0") else industry_name)

    company.set_if_empty("registered_industries", "; ".join(unique_keep_order(industries)[:MAX_INDUSTRIES]))
    company.add_source(SOURCE_NAME)
