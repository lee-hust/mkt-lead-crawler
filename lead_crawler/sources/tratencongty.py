"""
Nguồn đăng ký doanh nghiệp trên tratencongty.com, dùng theo 2 cách:

1. Nguồn bổ sung (enrich): tra theo MST (hoặc theo tên pháp lý nếu chưa có MST) để lấy
   người đại diện pháp luật, loại hình, ngày cấp phép, ngày hoạt động, trạng thái, ngành nghề VSIC.
2. Nguồn tìm công ty (iter_companies): duyệt danh sách công ty theo tỉnh/thành
   (mới đăng ký xếp trước), mỗi trang 50 công ty.

robots.txt cho phép mọi bot; site không có điều khoản cấm thu thập.
MST và SĐT trên site hiển thị bằng ảnh (site cố ý ẩn) nên không đọc; chỉ lấy dữ liệu dạng chữ.
Kết quả tìm kiếm đôi khi trả nhầm công ty (nhất là công ty mới), nên luôn đối chiếu tên.
"""

import itertools
import logging
import re
from datetime import date
from typing import Iterator, Optional
from urllib.parse import quote

from lead_crawler.html_soup import make_soup

from lead_crawler.http_client import HttpClient
from lead_crawler.models import CONTACT_TYPE_PERSON, Company, ContactPerson
from lead_crawler.sources.base import EnrichmentSource
from lead_crawler.text_utils import (
    LEGAL_NAME_MARKERS,
    clean_text,
    company_name_tokens,
    is_same_company_name,
    to_ascii_key,
)

logger = logging.getLogger(__name__)

HOST = "www.tratencongty.com"
BASE_URL = "https://www.tratencongty.com"
SEARCH_URL = BASE_URL + "/search/{query}/"
COMPANY_ID_REGEX = re.compile(r"/company/([0-9a-f]+)-")
LEGAL_REPRESENTATIVE_POSITION = "Người đại diện pháp luật"
MATCHED_BY_REGISTERED_ADDRESS = "Địa chỉ đăng ký"
MAX_INDUSTRIES = 100

# Đường dẫn trang danh sách theo tỉnh/thành trên tratencongty.com
PROVINCE_PATHS = {
    "ha-noi": "/thanh-pho-ha-noi/",
    "ho-chi-minh": "/thanh-pho-ho-chi-minh/",
    "da-nang": "/thanh-pho-da-nang/",
    "hai-phong": "/thanh-pho-hai-phong/",
    "can-tho": "/thanh-pho-can-tho/",
}


class TraTenCongTySource(EnrichmentSource):
    """
    Bổ sung người đại diện pháp luật và thông tin đăng ký kinh doanh; đồng thời tìm công ty theo tỉnh.
    """

    name = "Tra Tên Công Ty"
    uses_tax_code = True

    def __init__(
        self,
        http_client: HttpClient,
        delay_seconds: float,
        fetch_detail: bool,
        search_by_name: bool,
        cities: dict[str, list[str]],
    ):
        self.http_client = http_client
        self.fetch_detail = fetch_detail
        self.search_by_name = search_by_name
        self.cities = cities
        http_client.set_host_delay(
            HOST,
            delay_seconds,
        )

    def is_blocked(self) -> bool:
        """
        Site đã từ chối truy cập trong lần chạy này chưa.
        """
        return self.http_client.is_blocked(HOST)

    # ------------------------------------------------------------------ nguồn bổ sung

    def enrich(self, company: Company) -> list[ContactPerson]:
        """
        Tìm công ty (nếu chưa có link đăng ký), rồi đọc trang chi tiết.
        """
        if self.is_blocked():
            return []

        # Nguồn trước đã có đủ người đại diện + ngành nghề + trạng thái hoạt động: bỏ qua để đỡ 2 request.
        # Khi tắt VietQR, trạng thái chỉ lấy được ở đây nên công ty nào cũng được tra.
        if company.legal_representative and company.registered_industries and company.tax_status:
            return []

        if not company.registry_url and not self._search(company):
            return []

        missing_detail = not company.registered_industries or not company.legal_form or not company.tax_status
        if self.fetch_detail and missing_detail:
            detail_html = self.http_client.get_text(company.registry_url)
            if detail_html is not None:
                apply_detail_page(
                    company,
                    detail_html,
                )

        company.add_source(self.name)
        if not company.legal_representative:
            return []

        return [
            ContactPerson(
                full_name=company.legal_representative,
                position=LEGAL_REPRESENTATIVE_POSITION,
                contact_type=CONTACT_TYPE_PERSON,
                source=self.name,
                source_url=company.registry_url,
            )
        ]

    def _search(self, company: Company) -> bool:
        """
        Tìm theo MST; chưa có MST thì tìm theo tên pháp lý (chỉ nhận khi khớp duy nhất trong khu vực).
        """
        tax_code = re.sub(r"[^\d\-]", "", company.tax_code or "")
        if tax_code:
            search_html = self.http_client.get_text(SEARCH_URL.format(query=tax_code))
            matching_results = filter_results_by_name(
                parse_result_blocks(search_html),
                company.legal_name or company.company_name,
                False,
            )
        elif self.search_by_name and looks_like_legal_name(company.legal_name):
            search_html = self.http_client.get_text(SEARCH_URL.format(query=quote(company.legal_name)))
            matching_results = filter_by_city(
                filter_results_by_name(
                    parse_result_blocks(search_html),
                    company.legal_name,
                    True,
                ),
                self.cities.get(company.target_city, []),
            )
            if len(matching_results) > 1:
                logger.info("  %s: %d công ty trùng tên, bỏ qua vì không có MST", self.name, len(matching_results))
                matching_results = []
        else:
            return False

        if not matching_results:
            return False

        search_result = matching_results[0]
        company.registry_url = search_result["url"]
        company.set_if_empty("legal_representative", search_result["legal_representative"])
        company.set_if_empty("registered_address", search_result["address"])

        return True

    # ------------------------------------------------------------------ nguồn tìm công ty

    def iter_companies(
        self,
        cities: dict[str, list[str]],
        max_pages: Optional[int],
    ) -> Iterator[Company]:
        """
        Duyệt danh sách công ty theo tỉnh/thành, trả về công ty (tên, người đại diện, địa chỉ).
        Các trang xếp công ty mới đăng ký lên trước nên mỗi lần chạy lại sẽ thấy công ty mới.
        """
        for city_name, city_keys in cities.items():
            province_path = next((path for key, path in PROVINCE_PATHS.items() if key in city_keys), None)
            if province_path is None:
                logger.warning("%s: chưa có đường dẫn danh sách cho %s", self.name, city_name)
                continue

            seen_urls: set[str] = set()
            page_numbers = itertools.count(1) if max_pages is None else range(1, max_pages + 1)
            for page_number in page_numbers:
                page_url = f"{BASE_URL}{province_path}?page={page_number}"
                page_html = self.http_client.get_text(
                    page_url,
                    wait_if_rate_limited=True,
                )
                if page_html is None:
                    break

                result_blocks = [result for result in parse_result_blocks(page_html) if result["url"] not in seen_urls]
                if not result_blocks:
                    # Trang trống hoặc lặp lại nội dung trang trước (phân trang hỏng): dừng, tránh vòng lặp vô ích.
                    logger.info("[%s] %s trang %d không có công ty mới, dừng tỉnh này", self.name, city_name, page_number)
                    break

                seen_urls.update(result["url"] for result in result_blocks)
                logger.info("[%s] %s trang %d: %d công ty", self.name, city_name, page_number, len(result_blocks))
                for result in result_blocks:
                    yield company_from_result(
                        result,
                        city_name,
                    )

                if self.is_blocked():
                    return


def company_from_result(
    result: dict,
    city_name: str,
) -> Company:
    """
    Tạo Company từ một kết quả trong danh sách theo tỉnh.
    """
    company_id_match = COMPANY_ID_REGEX.search(result["url"])
    company_id = company_id_match.group(1) if company_id_match else result["url"]

    return Company(
        record_id=f"ttc:{company_id}",
        discovered_by=TraTenCongTySource.name,
        company_name=result["name"],
        legal_name=result["name"],
        legal_representative=result["legal_representative"],
        address=result["address"],
        registered_address=result["address"],
        city=city_name,
        target_city=city_name,
        matched_by=MATCHED_BY_REGISTERED_ADDRESS,
        search_category="Danh sách doanh nghiệp theo tỉnh (tratencongty)",
        registry_url=result["url"],
        sources=[TraTenCongTySource.name],
        crawled_at=date.today().isoformat(),
    )


def looks_like_legal_name(legal_name: str) -> bool:
    """
    Chỉ tra theo tên khi đó là tên pháp lý đầy đủ (Công ty ..., Doanh nghiệp ...), không phải tên thương hiệu.
    """
    return bool(legal_name) and legal_name.lower().startswith(LEGAL_NAME_MARKERS)


def normalize_person_name(name: str) -> str:
    """
    Tên viết hoa toàn bộ (NGUYỄN VĂN A) đổi về dạng Nguyễn Văn A.
    """
    name = clean_text(name)

    return name.title() if name.isupper() else name


def parse_labeled_lines(container) -> dict[str, str]:
    """
    Đọc các dòng dạng "Nhãn: giá trị" (ngăn cách bằng <br>) thành dict {nhãn không dấu: giá trị}.
    """
    values: dict[str, str] = {}
    for line in container.get_text("\n").splitlines():
        if ":" not in line:
            continue

        label, value = line.split(":", 1)
        label_key = to_ascii_key(label)
        value = clean_text(value)
        if label_key and value and label_key not in values:
            values[label_key] = value

    return values


def parse_result_blocks(page_html: Optional[str]) -> list[dict]:
    """
    Đọc các khối công ty (trang tìm kiếm hoặc danh sách theo tỉnh):
    [{"name", "url", "legal_representative", "address"}].
    """
    if not page_html:
        return []

    beautiful_soup = make_soup(page_html)
    results = []
    for result_tag in beautiful_soup.select("div.search-results"):
        anchor = result_tag.select_one('a[href*="/company/"]')
        if anchor is None:
            continue

        values = parse_labeled_lines(result_tag)
        results.append(
            {
                "name": clean_text(anchor.get_text()),
                "url": anchor["href"],
                "legal_representative": normalize_person_name(values.get("dai-dien-phap-luat", "")),
                "address": values.get("dia-chi", ""),
            }
        )

    return results


def filter_results_by_name(
    results: list[dict],
    reference_name: str,
    exact_name: bool,
) -> list[dict]:
    """
    Giữ kết quả có tên khớp reference_name. exact_name=True yêu cầu trùng toàn bộ từ đặc trưng
    (dùng khi tra theo tên, không có MST để đối chiếu).
    """
    reference_tokens = company_name_tokens(reference_name)
    matching_results = []
    for result in results:
        if exact_name:
            is_match = bool(reference_tokens) and company_name_tokens(result["name"]) == reference_tokens
        else:
            is_match = is_same_company_name(result["name"], reference_name)

        if is_match:
            matching_results.append(result)
        else:
            logger.debug("Bỏ kết quả lệch tên: %s <> %s", result["name"], reference_name)

    return matching_results


def filter_by_city(
    results: list[dict],
    city_keys: list[str],
) -> list[dict]:
    """
    Giữ kết quả có địa chỉ thuộc khu vực đang quét.
    """
    if not city_keys:
        return results

    return [result for result in results if any(key in to_ascii_key(result["address"]) for key in city_keys)]


def apply_detail_page(
    company: Company,
    detail_html: str,
) -> None:
    """
    Đọc khối thông tin đăng ký và bảng ngành nghề trên trang chi tiết (chỉ phần chữ).
    """
    beautiful_soup = make_soup(detail_html)
    info_tag = beautiful_soup.select_one("div.jumbotron")
    if info_tag is not None:
        values = parse_labeled_lines(info_tag)
        company.set_if_empty("legal_representative", normalize_person_name(values.get("dai-dien-phap-luat", "")))
        company.set_if_empty("legal_form", values.get("loai-hinh-hoat-dong", ""))
        company.set_if_empty("license_date", values.get("ngay-cap-giay-phep", ""))
        operating_text = values.get("ngay-hoat-dong", "")
        company.set_if_empty("operating_since", operating_text.split("(", 1)[0].strip())
        years_match = re.search(r"(\d+)\s*năm", operating_text)
        if years_match:
            company.set_if_empty("years_active", years_match.group(1))

        company.set_if_empty("registered_address", values.get("dia-chi", ""))
        company.set_if_empty("tax_status", values.get("trang-thai", ""))
        company.set_if_empty("international_name", values.get("ten-giao-dich", ""))

    industries = []
    for table in beautiful_soup.select("table"):
        header_text = to_ascii_key(" ".join(th.get_text() for th in table.select("th")))
        if "ma-nganh" not in header_text:
            continue

        for row in table.select("tbody tr"):
            cells = [clean_text(cell.get_text()) for cell in row.select("td")]
            if len(cells) >= 3 and cells[1]:
                industries.append(f"{cells[2]} {cells[1]}".strip())

    company.set_if_empty("registered_industries", "; ".join(industries[:MAX_INDUSTRIES]))
    if industries:
        company.set_if_empty("industry", industries[0].split(" ", 1)[-1])
