"""
Cấu hình mặc định: sửa ở đây rồi Run main.py. Ghi đè bằng tham số dòng lệnh: python main.py --help.
"""

# Tỉnh/TP cần quét (tên trong ALL_CITIES, quét theo thứ tự); ["all"] = mọi tỉnh trong ALL_CITIES.
SELECTED_CITIES = ["Hà Nội", "TP. Hồ Chí Minh", "Cần Thơ", "Đà Nẵng", "Hải Phòng"]

# Tỉnh/TP theo địa giới mới (sau sáp nhập 7/2025). Thêm tỉnh: tên -> đường dẫn trên infodoanhnghiep.com
# (vd. "Ha-Noi" trong https://infodoanhnghiep.com/Ha-Noi/), số trang danh sách tối đa (20 công ty / trang; bỏ trống =
# DIRECTORY_MAX_PAGES_PER_CITY) và từ khóa không dấu của các tỉnh cũ gộp vào (để nhận ra tỉnh trong địa chỉ cũ và
# tra tratencongty, vẫn chia theo 63 tỉnh cũ). Hiện tại 5.000 trang ~ 100.000 công ty, chia theo quy mô từng TP trên site
# (HCM ~646 nghìn, Hà Nội ~340 nghìn, Hải Phòng ~75 nghìn, Đà Nẵng ~69 nghìn, Cần Thơ ~38 nghìn), TP nhỏ được nâng lên.
ALL_CITIES = {
    "Hà Nội": {"infodoanhnghiep": "Ha-Noi", "pages": 1500, "keys": ["ha-noi"]},
    "TP. Hồ Chí Minh": {
        "infodoanhnghiep": "TP-Ho-Chi-Minh",
        "pages": 2000,
        "keys": ["ho-chi-minh", "tphcm", "tp-hcm", "binh-duong", "ba-ria-vung-tau", "brvt"],
    },
    "Cần Thơ": {"infodoanhnghiep": "Can-Tho", "pages": 400, "keys": ["can-tho", "soc-trang", "hau-giang"]},
    "Đà Nẵng": {"infodoanhnghiep": "Da-Nang", "pages": 550, "keys": ["da-nang", "quang-nam"]},
    "Hải Phòng": {"infodoanhnghiep": "Hai-Phong", "pages": 550, "keys": ["hai-phong", "hai-duong"]},
}

# ============================================================ TÌM CÔNG TY

# File CSV danh sách công ty có sẵn (mẫu: input_template.csv); "" = không dùng.
INPUT_FILE = ""

# Nguồn tự tìm công ty, chạy theo thứ tự: "infodoanhnghiep" (có MST, địa giới mới), "tratencongty" (không có MST).
DISCOVERY_SOURCES = ["infodoanhnghiep"]

# Số trang tối đa mỗi tỉnh khi ALL_CITIES không ghi "pages" (None = không giới hạn); --directory-pages N ghi đè cho mọi
# tỉnh. infodoanhnghiep quét xen kẽ các tỉnh, chạy lại thì đọc tiếp (output/tien_do_infodoanhnghiep.json).
# tratencongty: 50 công ty / trang.
DIRECTORY_MAX_PAGES_PER_CITY = None
REGISTRY_MAX_PAGES_PER_CITY = None

# Chỉ giữ công ty có tên / ngành nghề chứa một trong các từ khóa (không phân biệt dấu); [] = giữ tất cả.
KEYWORDS: list[str] = []

# ============================================================ NGUỒN BỔ SUNG

# VietQR (Cục Thuế): tên pháp lý, trạng thái. Mặc định tắt (bật bằng --vietqr): infodoanhnghiep đã có trạng thái
# người nộp thuế đối chiếu với Cơ quan thuế. VietQR giới hạn ~1 lượt / phút mỗi IP, API miễn phí dừng 31/12/2026.
USE_VIETQR_TAX_LOOKUP = False
# Giai đoạn 1 không chờ VietQR (hết lượt thì bỏ qua); giai đoạn 2 tra bù sau khi cào (--vietqr-backfill).
VIETQR_WAIT_IF_RATE_LIMITED = False
VIETQR_BACKFILL_AFTER_CRAWL = True
# Xoay vòng VietQR qua proxy miễn phí (swiftshadow), mặc định tắt, bật bằng --vietqr-free-proxies.
# Proxy miễn phí không rõ chủ, nên hỏi IT trước khi bật trên server công ty.
VIETQR_FREE_PROXIES = False
VIETQR_FREE_PROXY_MAX = 100             # số proxy lấy về mỗi lần
VIETQR_FREE_PROXY_MIN = 10              # còn ít hơn thì lấy thêm
VIETQR_FREE_PROXY_REFRESH_MINUTES = 10  # khoảng cách tối thiểu giữa hai lần lấy
# infodoanhnghiep.com: dữ liệu thuế, số lao động, cơ quan thuế, ngành nghề; giai đoạn 2 tra ở đây trước VietQR.
# Điều khoản của site cấm thu thập tự động cho mục đích thương mại.
USE_INFODOANHNGHIEP = True
INFODOANHNGHIEP_DELAY_SECONDS = 2
# doanhnghiep.biz: số điện thoại dạng chữ, người đại diện, tình trạng (email bị mã hóa nên không lấy).
USE_DOANHNGHIEP_BIZ = True
DOANHNGHIEP_BIZ_DELAY_SECONDS = 2
USE_TRATENCONGTY = True             # người đại diện, loại hình, trạng thái, ngành nghề
TRATENCONGTY_FETCH_DETAIL = True
TRATENCONGTY_SEARCH_BY_NAME = True  # chưa có MST thì tra theo tên (chỉ nhận khi khớp duy nhất)
ENRICH_FROM_WEBSITE = True          # website công ty: email, SĐT, lãnh đạo, MST

# ============================================================ CHUNG

# Dừng sau khi ghi được bấy nhiêu công ty; None = không giới hạn.
MAX_COMPANIES = None

# Giãn cách giữa hai request tới cùng một site (giây). Giảm xuống dễ bị chặn.
VIETQR_DELAY_SECONDS = 2
TRATENCONGTY_DELAY_SECONDS = 3
WEBSITE_DELAY_SECONDS = 1.5
WEBSITE_MAX_PAGES = 10              # số trang con của website đọc thêm ngoài trang chủ

REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3

# Khai báo trung thực là bot, không giả trình duyệt.
USER_AGENT = "Mozilla/5.0 (compatible; MktLeadCrawler/1.0)"

# Thư mục kết quả (tương đối so với thư mục dự án).
OUTPUT_DIR = "output"
# Chỉ ghi companies.csv (người liên hệ gộp ở cột Liên hệ & chức vụ). True / --contacts-file: ghi thêm contacts.csv
# (mỗi dòng một người), có ích khi dùng --input có website (nhiều người, SĐT / email riêng).
WRITE_CONTACTS_FILE = False
