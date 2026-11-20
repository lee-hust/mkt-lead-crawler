"""
Giao diện chung cho các nguồn bổ sung dữ liệu.
"""

from abc import ABC, abstractmethod

from lead_crawler.models import Company, ContactPerson


class EnrichmentSource(ABC):
    """
    Nguồn bổ sung: nhận một Company đã có, điền thêm các trường còn trống
    và trả về danh sách người liên hệ tìm được ở nguồn đó.
    """

    name: str = ""

    # True nếu nguồn tra theo MST: khi nguồn chạy sau (vd. website) tìm ra MST,
    # pipeline sẽ chạy lại nguồn này một lần nữa.
    uses_tax_code: bool = False

    @abstractmethod
    def enrich(self, company: Company) -> list[ContactPerson]:
        """
        Bổ sung dữ liệu cho company; trả về [] nếu không tìm thấy gì.
        """
        raise NotImplementedError
