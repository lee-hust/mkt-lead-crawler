"""
Giao diện chung cho các nguồn bổ sung dữ liệu.
"""

from abc import ABC, abstractmethod

from lead_crawler.models import Company, ContactPerson


class EnrichmentSource(ABC):
    """
    Nguồn bổ sung: điền trường còn trống của Company, trả về người liên hệ tìm được.
    """

    name: str = ""

    # True nếu tra theo MST: MST tìm ra muộn thì pipeline chạy lại nguồn này.
    uses_tax_code: bool = False

    @abstractmethod
    def enrich(self, company: Company) -> list[ContactPerson]:
        """
        Bổ sung dữ liệu cho company; trả về [] nếu không tìm thấy gì.
        """
        raise NotImplementedError
