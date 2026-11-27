"""
Cấu hình mặc định: sửa ở đây rồi Run main.py. Ghi đè bằng tham số dòng lệnh: python main.py --help.
"""

# Khu vực cần quét (tên trong ALL_CITIES, quét theo thứ tự). Cả nước: ["all"].
SELECTED_CITIES = ["Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng"]

# 63 tỉnh/thành theo địa giới cũ (các site chưa cập nhật sáp nhập 7/2025).
# Tên hiển thị -> từ khóa không dấu (từ khóa đầu là đường dẫn trên site). Không đổi tên hiển thị của tỉnh đã quét.
ALL_CITIES = {
    "Hà Nội": ["ha-noi"],
    "TP. Hồ Chí Minh": ["ho-chi-minh", "tphcm", "tp-hcm"],
    "Đà Nẵng": ["da-nang"],
    "Hải Phòng": ["hai-phong"],
    "Cần Thơ": ["can-tho"],
    "An Giang": ["an-giang"],
    "Bà Rịa - Vũng Tàu": ["ba-ria-vung-tau", "brvt"],
    "Bắc Giang": ["bac-giang"],
    "Bắc Kạn": ["bac-kan", "bac-can"],
    "Bạc Liêu": ["bac-lieu"],
    "Bắc Ninh": ["bac-ninh"],
    "Bến Tre": ["ben-tre"],
    "Bình Định": ["binh-dinh"],
    "Bình Dương": ["binh-duong"],
    "Bình Phước": ["binh-phuoc"],
    "Bình Thuận": ["binh-thuan"],
    "Cà Mau": ["ca-mau"],
    "Cao Bằng": ["cao-bang"],
    "Đắk Lắk": ["dak-lak"],
    "Đắk Nông": ["dak-nong"],
    "Điện Biên": ["dien-bien"],
    "Đồng Nai": ["dong-nai"],
    "Đồng Tháp": ["dong-thap"],
    "Gia Lai": ["gia-lai"],
    "Hà Giang": ["ha-giang"],
    "Hà Nam": ["ha-nam"],
    "Hà Tĩnh": ["ha-tinh"],
    "Hải Dương": ["hai-duong"],
    "Hậu Giang": ["hau-giang"],
    "Hòa Bình": ["hoa-binh"],
    "Hưng Yên": ["hung-yen"],
    "Khánh Hòa": ["khanh-hoa"],
    "Kiên Giang": ["kien-giang"],
    "Kon Tum": ["kon-tum"],
    "Lai Châu": ["lai-chau"],
    "Lâm Đồng": ["lam-dong"],
    "Lạng Sơn": ["lang-son"],
    "Lào Cai": ["lao-cai"],
    "Long An": ["long-an"],
    "Nam Định": ["nam-dinh"],
    "Nghệ An": ["nghe-an"],
    "Ninh Bình": ["ninh-binh"],
    "Ninh Thuận": ["ninh-thuan"],
    "Phú Thọ": ["phu-tho"],
    "Phú Yên": ["phu-yen"],
    "Quảng Bình": ["quang-binh"],
    "Quảng Nam": ["quang-nam"],
    "Quảng Ngãi": ["quang-ngai"],
    "Quảng Ninh": ["quang-ninh"],
    "Quảng Trị": ["quang-tri"],
    "Sóc Trăng": ["soc-trang"],
    "Sơn La": ["son-la"],
    "Tây Ninh": ["tay-ninh"],
    "Thái Bình": ["thai-binh"],
    "Thái Nguyên": ["thai-nguyen"],
    "Thanh Hóa": ["thanh-hoa"],
    "Thừa Thiên Huế": ["thua-thien-hue", "thanh-pho-hue", "tp-hue"],
    "Tiền Giang": ["tien-giang"],
    "Trà Vinh": ["tra-vinh"],
    "Tuyên Quang": ["tuyen-quang"],
    "Vĩnh Long": ["vinh-long"],
    "Vĩnh Phúc": ["vinh-phuc"],
    "Yên Bái": ["yen-bai"],
}

# ============================================================ TÌM CÔNG TY

# File CSV danh sách công ty có sẵn (mẫu: input_template.csv); "" = không dùng.
INPUT_FILE = ""

# Nguồn tự tìm công ty, chạy theo thứ tự: "doanhnghiep_me" (có MST, SĐT), "tratencongty" (không có MST/SĐT).
DISCOVERY_SOURCES = ["doanhnghiep_me", "tratencongty"]

# Số trang tối đa mỗi tỉnh (None = không giới hạn). doanhnghiep.me: trang địa bàn ~20 công ty; tratencongty: 50 công ty.
DIRECTORY_MAX_PAGES_PER_CITY = None
REGISTRY_MAX_PAGES_PER_CITY = None

# Chỉ giữ công ty có tên / ngành nghề chứa một trong các từ khóa (không phân biệt dấu); [] = giữ tất cả.
KEYWORDS: list[str] = []

# ============================================================ NGUỒN BỔ SUNG

# VietQR (Cục Thuế): tên pháp lý, trạng thái. Giới hạn lượt theo IP (~1 lượt / phút từ 27/11/2026).
USE_VIETQR_TAX_LOOKUP = True
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
DOANHNGHIEP_ME_FETCH_DETAIL = True  # trang chi tiết: người đại diện, tên viết tắt, ngành nghề
USE_TRATENCONGTY = True             # người đại diện, loại hình, trạng thái, ngành nghề
TRATENCONGTY_FETCH_DETAIL = True
TRATENCONGTY_SEARCH_BY_NAME = True  # chưa có MST thì tra theo tên (chỉ nhận khi khớp duy nhất)
ENRICH_FROM_WEBSITE = True          # website công ty: email, SĐT, lãnh đạo, MST

# ============================================================ CHUNG

# Dừng sau khi ghi được bấy nhiêu công ty; None = không giới hạn.
MAX_COMPANIES = None

# Giãn cách giữa hai request tới cùng một site (giây). Giảm xuống dễ bị chặn.
VIETQR_DELAY_SECONDS = 2
DOANHNGHIEP_ME_DELAY_SECONDS = 2
TRATENCONGTY_DELAY_SECONDS = 3
WEBSITE_DELAY_SECONDS = 1.5
WEBSITE_MAX_PAGES = 10              # số trang con của website đọc thêm ngoài trang chủ

REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3

# Khai báo trung thực là bot, không giả trình duyệt.
USER_AGENT = "Mozilla/5.0 (compatible; MktLeadCrawler/1.0)"

# Thư mục kết quả (tương đối so với thư mục dự án).
OUTPUT_DIR = "output"
