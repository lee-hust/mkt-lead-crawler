"""
doanhnghiep.biz: tra theo MST (tìm kiếm -> trang công ty) lấy số điện thoại dạng chữ, người đại diện, tình trạng.
Email trên site bị Cloudflare mã hóa (chống thu thập) nên không lấy.
"""

import logging
import re
from typing import Optional

from lead_crawler.html_soup import make_soup
from lead_crawler.http_client import HttpClient
from lead_crawler.models import CONTACT_TYPE_PERSON, TAX_CODE_SOURCE_WEBSITE, Company, ContactPerson
from lead_crawler.sources.base import EnrichmentSource
from lead_crawler.text_utils import clean_text, extract_phones, is_same_company_name

logger = logging.getLogger(__name__)

HOST = "doanhnghiep.biz"
BASE_URL = "https://doanhnghiep.biz"
SEARCH_URL = BASE_URL + "/tim-kiem/?timkiem={tax_code}"
LEGAL_REPRESENTATIVE_POSITION = "Người đại diện pháp luật"


class DoanhNghiepBizSource(EnrichmentSource):
    """
    Số điện thoại, người đại diện, tình trạng, loại hình theo MST từ doanhnghiep.biz.
    """

    name = "doanhnghiep.biz"
    uses_tax_code = True

    def __init__(
        self,
        http_client: HttpClient,
        delay_seconds: float,
        wait_if_rate_limited: bool,
    ):
        self.http_client = http_client
        self.wait_if_rate_limited = wait_if_rate_limited
        http_client.set_host_delay(
            HOST,
            delay_seconds,
        )

    def is_blocked(self) -> bool:
        """
        Site đã từ chối truy cập trong lần chạy này chưa.
        """
        return self.http_client.is_blocked(HOST)

    def enrich(self, company: Company) -> list[ContactPerson]:
        """
        Tìm trang công ty theo MST rồi đọc bảng thông tin; bỏ qua nếu đã đủ SĐT, người đại diện, tình trạng.
        """
        tax_code = re.sub(r"[^\d\-]", "", company.tax_code or "")
        if not tax_code or self.is_blocked():
            return []

        if company.phone and company.legal_representative and company.tax_status:
            return []

        detail_url = company.doanhnghiep_biz_url or self._find_detail_url(tax_code)
        if not detail_url:
            return []

        detail_html = self.http_client.get_text(
            detail_url,
            wait_if_rate_limited=self.wait_if_rate_limited,
        )
        if detail_html is None:
            return []

        values = parse_company_table(detail_html)
        page_tax_code = re.sub(r"[^\d\-]", "", values.get("taxID", ""))
        if page_tax_code and page_tax_code != tax_code:
            return []

        # MST lấy từ website có thể là của đơn vị khác, phải khớp tên mới nhận.
        if company.tax_code_source == TAX_CODE_SOURCE_WEBSITE:
            known_names = [company.legal_name, company.company_name, company.brand_name]
            if not any(is_same_company_name(values.get("name", ""), known_name) for known_name in known_names if known_name):
                logger.info("  MST %s trên website là của '%s' (doanhnghiep.biz), không khớp, bỏ MST này", tax_code, values.get("name"))
                company.tax_code = ""
                company.tax_code_source = ""

                return []

        phones = extract_phones(values.get("Phone", ""))
        company.set_if_empty("phone", phones[0] if phones else "")
        company.set_if_empty("legal_representative", values.get("Owner", ""))
        company.set_if_empty("tax_status", values.get("Status", ""))
        company.set_if_empty("legal_form", values.get("BusinessClass", ""))
        company.set_if_empty("license_date", values.get("IncorporatedDate", ""))
        company.set_if_empty("operating_since", values.get("StartDate", ""))
        company.set_if_empty("international_name", values.get("alternateName", ""))
        company.set_if_empty("registered_address", values.get("address", ""))
        company.doanhnghiep_biz_url = detail_url
        company.add_source(self.name)
        if not values.get("Owner"):
            return []

        return [
            ContactPerson(
                full_name=values["Owner"],
                position=LEGAL_REPRESENTATIVE_POSITION,
                contact_type=CONTACT_TYPE_PERSON,
                source=self.name,
                source_url=detail_url,
            )
        ]

    def _find_detail_url(self, tax_code: str) -> Optional[str]:
        """
        Tìm theo MST, chỉ nhận link đúng MST đó (không nhận link chi nhánh của MST mẹ).
        """
        search_html = self.http_client.get_text(
            SEARCH_URL.format(tax_code=tax_code),
            wait_if_rate_limited=self.wait_if_rate_limited,
        )
        if search_html is None:
            return None

        return find_detail_url(
            search_html,
            tax_code,
        )


def find_detail_url(
    search_html: str,
    tax_code: str,
) -> Optional[str]:
    """
    Link trang công ty có dạng /<MST>-<tên>; chi nhánh của MST mẹ có dạng /<MST>-<3 số>-<tên> nên bị bỏ.
    """
    prefix = f"/{tax_code}-"
    branch_pattern = re.compile(rf"^/{re.escape(tax_code)}-\d{{3}}-")
    for link in make_soup(search_html).find_all("a", href=True):
        href = link["href"].replace(BASE_URL, "")
        if href.startswith(prefix) and not branch_pattern.match(href):
            return BASE_URL + href

    return None


def parse_company_table(detail_html: str) -> dict[str, str]:
    """
    Đọc bảng company-table theo itemprop: name, alternateName, taxID, IncorporatedDate, StartDate, Status,
    address, Owner, Phone, BusinessClass. Bỏ ô email (bị mã hóa).
    """
    beautiful_soup = make_soup(detail_html)
    table = beautiful_soup.select_one("table.company-table")
    if table is None:
        return {}

    values: dict[str, str] = {}
    name_tag = table.select_one('[itemprop="name"]')
    if name_tag is not None:
        values["name"] = clean_text(name_tag.get_text(" "))

    for item in table.select("td[itemprop], span[itemprop]"):
        item_name = item.get("itemprop")
        if item_name in ("Email", "email") or item_name in values:
            continue

        value = clean_text(item.get_text(" "))
        if value:
            values[item_name] = value

    return values
