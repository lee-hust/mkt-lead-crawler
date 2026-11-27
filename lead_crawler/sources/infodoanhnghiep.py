"""
infodoanhnghiep.com: tra theo MST (tìm kiếm -> trang chi tiết) lấy dữ liệu thuế, số lao động, ngành nghề.
Không lấy số tài khoản ngân hàng.
"""

import logging
import re
from typing import Optional

from lead_crawler.html_soup import make_soup
from lead_crawler.http_client import HttpClient
from lead_crawler.models import TAX_CODE_SOURCE_WEBSITE, Company, ContactPerson
from lead_crawler.sources.base import EnrichmentSource
from lead_crawler.sources.vietqr import VietQrSource
from lead_crawler.text_utils import clean_text, is_same_company_name, to_ascii_key

logger = logging.getLogger(__name__)

HOST = "infodoanhnghiep.com"
BASE_URL = "https://infodoanhnghiep.com"
SEARCH_URL = BASE_URL + "/tim-kiem/auto/{tax_code}/"
DETAIL_HEADING = "thong-tin-chi-tiet"
INDUSTRY_HEADING = "nganh-nghe-kinh-doanh"
MAIN_INDUSTRY_MARK = "(Ngành chính)"
MAX_INDUSTRIES = 100
BRANCH_COUNT_PATTERN = re.compile(r"có\s+([\d.,]+)\s+chi nhánh", re.IGNORECASE)


class InfoDoanhNghiepSource(EnrichmentSource):
    """
    Dữ liệu đăng ký thuế theo MST từ infodoanhnghiep.com.
    """

    name = "infodoanhnghiep.com"
    uses_tax_code = True

    def __init__(
        self,
        http_client: HttpClient,
        delay_seconds: float,
        wait_if_rate_limited: bool,
        overwrite_existing: bool = False,
    ):
        """
        overwrite_existing=True (giai đoạn 2): ghi đè trạng thái / tên quốc tế, trừ công ty đã có dữ liệu VietQR.
        """
        self.http_client = http_client
        self.wait_if_rate_limited = wait_if_rate_limited
        self.overwrite_existing = overwrite_existing
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
        Tìm trang chi tiết theo MST rồi đọc dữ liệu đăng ký thuế. Site không có người liên hệ nên luôn trả về [].
        """
        tax_code = re.sub(r"[^\d\-]", "", company.tax_code or "")
        if not tax_code or self.is_blocked():
            return []

        detail_url = company.infodoanhnghiep_url or self._find_detail_url(tax_code)
        if not detail_url:
            return []

        detail_html = self.http_client.get_text(
            detail_url,
            wait_if_rate_limited=self.wait_if_rate_limited,
        )
        if detail_html is None:
            return []

        info_page = parse_detail_page(detail_html)
        page_tax_code = re.sub(r"[^\d\-]", "", info_page.values.get("ma-so-thue", ""))
        if page_tax_code and page_tax_code != tax_code:
            logger.info("  infodoanhnghiep: trang %s là của MST %s, không phải %s, bỏ qua", detail_url, page_tax_code, tax_code)

            return []

        legal_name = info_page.values.get("ten-doanh-nghiep", "")

        # MST đọc từ website chưa chắc là của công ty này (có thể là MST đơn vị làm web...), nên phải khớp tên mới nhận.
        if company.tax_code_source == TAX_CODE_SOURCE_WEBSITE:
            known_names = [company.legal_name, company.company_name, company.brand_name]
            if not any(is_same_company_name(legal_name, known_name) for known_name in known_names if known_name):
                logger.info("  MST %s trên website là của '%s' (infodoanhnghiep), không khớp, bỏ MST này", tax_code, legal_name)
                company.tax_code = ""
                company.tax_code_source = ""

                return []

        self._apply(
            company,
            info_page,
        )
        company.infodoanhnghiep_url = detail_url
        company.add_source(self.name)

        return []

    def _find_detail_url(self, tax_code: str) -> Optional[str]:
        """
        Tìm theo MST, chỉ nhận kết quả có đúng MST đó. Không thấy thì trả về None.
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

    def _apply(
        self,
        company: Company,
        info_page: "InfoPage",
    ) -> None:
        """
        Tên pháp lý / trạng thái / tên quốc tế ghi đè như VietQR (trừ khi đã có VietQR); trường khác chỉ điền khi trống.
        """
        values = info_page.values
        has_vietqr_data = VietQrSource.name in company.sources
        legal_name = values.get("ten-doanh-nghiep", "")
        if legal_name and not has_vietqr_data:
            company.legal_name = legal_name
        else:
            company.set_if_empty("legal_name", legal_name)

        is_overwrite = self.overwrite_existing and not has_vietqr_data
        tax_status = values.get("tinh-trang-nguoi-nop-thue") or values.get("tinh-trang-hoat-dong", "")
        international_name = values.get("ten-quoc-te", "")
        for attribute_name, value in (("tax_status", tax_status), ("international_name", international_name)):
            if is_overwrite and value:
                setattr(company, attribute_name, value)
            else:
                company.set_if_empty(attribute_name, value)

        company.set_if_empty("short_name", values.get("ten-giao-dich", ""))
        company.set_if_empty("tax_office", values.get("noi-dang-ky-quan-ly", ""))
        company.set_if_empty("registered_address", values.get("dia-chi", ""))
        company.set_if_empty("license_date", values.get("ngay-cap-giay-phep", ""))
        company.set_if_empty("operating_since", values.get("ngay-bat-dau-hoat-dong", ""))
        company.set_if_empty("employee_count", re.sub(r"[^\d]", "", values.get("so-lao-dong", "")))
        company.set_if_empty("branch_count", info_page.branch_count)
        company.set_if_empty("registered_industries", "; ".join(info_page.industries[:MAX_INDUSTRIES]))
        company.set_if_empty("industry", info_page.main_industry)


class InfoPage:
    """
    Dữ liệu đọc được từ một trang chi tiết: các cặp nhãn / giá trị, ngành nghề, số chi nhánh.
    """

    def __init__(
        self,
        values: dict[str, str],
        industries: list[str],
        main_industry: str,
        branch_count: str,
    ):
        self.values = values
        self.industries = industries
        self.main_industry = main_industry
        self.branch_count = branch_count


def find_detail_url(
    search_html: str,
    tax_code: str,
) -> Optional[str]:
    """
    Trong trang kết quả tìm kiếm, lấy link trang chi tiết của kết quả có đúng MST.
    """
    beautiful_soup = make_soup(search_html)
    for company_item in beautiful_soup.select("div.company-item"):
        item_text = clean_text(company_item.get_text(" "))
        tax_code_match = re.search(r"Mã số thuế:\s*([\d\-]+)", item_text)
        link = company_item.select_one('a[href*="/thong-tin/"]')
        if tax_code_match and link and tax_code_match.group(1) == tax_code:
            return absolute_url(link["href"])

    return None


def parse_detail_page(detail_html: str) -> InfoPage:
    """
    Đọc khối "Thông tin chi tiết" và "Ngành nghề kinh doanh"; bỏ ô tài khoản ngân hàng.
    """
    beautiful_soup = make_soup(detail_html)
    for small_tag in beautiful_soup.select("small"):
        small_tag.decompose()

    values: dict[str, str] = {}
    industries: list[str] = []
    main_industry = ""
    for section in beautiful_soup.select("div.company-info-section"):
        heading = section.find("h2")
        heading_key = to_ascii_key(heading.get_text(" ")) if heading else ""
        pairs = read_cell_pairs(section)
        if heading_key == DETAIL_HEADING:
            for label, value in pairs:
                label_key = to_ascii_key(label)
                if label_key and value and not label_key.startswith("tk-ngan-hang") and label_key not in values:
                    values[label_key] = value
        elif heading_key == INDUSTRY_HEADING:
            for industry_code, industry_text in pairs:
                if not industry_code.isdigit():
                    continue

                is_main = MAIN_INDUSTRY_MARK in industry_text
                industry_name = clean_text(industry_text.replace(MAIN_INDUSTRY_MARK, ""))
                industries.append(f"{industry_code} {industry_name}")
                if is_main and not main_industry:
                    main_industry = industry_name

    branch_match = BRANCH_COUNT_PATTERN.search(clean_text(beautiful_soup.get_text(" ")))
    branch_count = re.sub(r"[^\d]", "", branch_match.group(1)) if branch_match else ""

    return InfoPage(
        values,
        industries,
        main_industry,
        branch_count,
    )


def read_cell_pairs(section) -> list[tuple[str, str]]:
    """
    Bảng dạng ô nối tiếp: ô nhãn (responsive-table-cell-head) rồi tới ô giá trị. Trả về [(nhãn, giá trị)].
    """
    pairs: list[tuple[str, str]] = []
    current_label: Optional[str] = None
    for cell in section.select("div.responsive-table-cell"):
        cell_text = clean_text(cell.get_text(" "))
        if "responsive-table-cell-head" in (cell.get("class") or []):
            current_label = cell_text.rstrip(":").strip()
            continue

        if current_label is not None:
            pairs.append((current_label, cell_text))
            current_label = None

    return pairs


def absolute_url(href: str) -> str:
    """
    Đổi link tương đối của site thành link đầy đủ.
    """
    if href.startswith("http"):
        return href

    return BASE_URL + "/" + href.lstrip("/")
