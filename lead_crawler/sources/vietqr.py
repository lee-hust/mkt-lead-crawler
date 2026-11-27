"""
VietQR: tra MST qua API công khai (dữ liệu Cục Thuế) lấy tên pháp lý, địa chỉ, trạng thái.
"""

import logging
import re

from lead_crawler.http_client import HttpClient
from lead_crawler.models import TAX_CODE_SOURCE_WEBSITE, Company, ContactPerson
from lead_crawler.sources.base import EnrichmentSource
from lead_crawler.text_utils import clean_text, is_same_company_name

logger = logging.getLogger(__name__)

API_HOST = "api.vietqr.io"
API_URL = "https://api.vietqr.io/v2/business/{tax_code}"


class VietQrSource(EnrichmentSource):
    """
    Bổ sung tên pháp lý, tên tiếng Anh, tên viết tắt, địa chỉ đăng ký thuế, trạng thái MST.
    """

    name = "VietQR (Cục Thuế)"
    uses_tax_code = True

    def __init__(
        self,
        http_client: HttpClient,
        delay_seconds: float,
        wait_if_rate_limited: bool,
        overwrite_existing: bool = False,
    ):
        """
        overwrite_existing=True (giai đoạn 2): ghi đè dữ liệu nguồn khác đã điền bằng dữ liệu Cục Thuế.
        """
        self.http_client = http_client
        self.wait_if_rate_limited = wait_if_rate_limited
        self.overwrite_existing = overwrite_existing
        http_client.set_host_delay(
            API_HOST,
            delay_seconds,
        )

    def enrich(self, company: Company) -> list[ContactPerson]:
        """
        Tra MST; dữ liệu Cục Thuế là nguồn chính thức nên được ghi đè tên pháp lý.
        """
        tax_code = re.sub(r"[^\d\-]", "", company.tax_code or "")
        if not tax_code or self.http_client.is_blocked(API_HOST):
            return []

        payload = self.http_client.get_json(
            API_URL.format(tax_code=tax_code),
            wait_if_rate_limited=self.wait_if_rate_limited,
        )
        if not payload or payload.get("code") != "00":
            return []

        data = payload.get("data") or {}
        legal_name = clean_text(data.get("name"))

        # MST lấy từ website có thể là của đơn vị khác, phải khớp tên mới nhận.
        if company.tax_code_source == TAX_CODE_SOURCE_WEBSITE:
            known_names = [company.legal_name, company.company_name, company.brand_name]
            if not any(is_same_company_name(legal_name, known_name) for known_name in known_names if known_name):
                logger.info("  MST %s trên website là của '%s', không khớp, bỏ MST này", tax_code, legal_name)
                company.tax_code = ""
                company.tax_code_source = ""

                return []

        if legal_name:
            company.legal_name = legal_name

        self._assign(company, "international_name", clean_text(data.get("internationalName")))
        self._assign(company, "short_name", clean_text(data.get("shortName")))
        self._assign(company, "tax_status", clean_text(data.get("status")))
        # Địa chỉ đăng ký thường đã có từ trang danh sách (chạy trước VietQR), nên chỉ điền khi còn trống.
        company.set_if_empty("registered_address", clean_text(data.get("address")))
        company.add_source(self.name)

        return []

    def _assign(
        self,
        company: Company,
        attribute_name: str,
        value: str,
    ) -> None:
        """
        Điền giá trị từ Cục Thuế: ghi đè khi tra bù, còn bình thường chỉ điền khi trường đang trống.
        """
        if self.overwrite_existing and value:
            setattr(company, attribute_name, value)

            return

        company.set_if_empty(attribute_name, value)
