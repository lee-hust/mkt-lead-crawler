"""
Slug tỉnh/thành của doanhnghiep.me và tratencongty.com (63 tỉnh/thành cũ).
"""

from typing import Optional

PROVINCE_SLUGS = frozenset(
    {
        "an-giang", "ba-ria-vung-tau", "bac-giang", "bac-kan", "bac-lieu", "bac-ninh", "ben-tre",
        "binh-dinh", "binh-duong", "binh-phuoc", "binh-thuan", "ca-mau", "can-tho", "cao-bang",
        "da-nang", "dak-lak", "dak-nong", "dien-bien", "dong-nai", "dong-thap", "gia-lai",
        "ha-giang", "ha-nam", "ha-noi", "ha-tinh", "hai-duong", "hai-phong", "hau-giang",
        "ho-chi-minh", "hoa-binh", "hung-yen", "khanh-hoa", "kien-giang", "kon-tum", "lai-chau",
        "lam-dong", "lang-son", "lao-cai", "long-an", "nam-dinh", "nghe-an", "ninh-binh",
        "ninh-thuan", "phu-tho", "phu-yen", "quang-binh", "quang-nam", "quang-ngai", "quang-ninh",
        "quang-tri", "soc-trang", "son-la", "tay-ninh", "thai-binh", "thai-nguyen", "thanh-hoa",
        "thua-thien-hue", "tien-giang", "tra-vinh", "tuyen-quang", "vinh-long", "vinh-phuc", "yen-bai",
    }
)

# Thành phố trực thuộc trung ương: tratencongty.com dùng tiền tố "thanh-pho-" thay vì "tinh-".
CENTRAL_CITY_SLUGS = frozenset({"ha-noi", "ho-chi-minh", "da-nang", "hai-phong", "can-tho"})


def find_province_slug(city_keys: list[str]) -> Optional[str]:
    """
    Lấy slug tỉnh/thành từ danh sách từ khóa của một khu vực (config.ALL_CITIES); không có thì trả về None.
    """

    return next((city_key for city_key in city_keys if city_key in PROVINCE_SLUGS), None)
