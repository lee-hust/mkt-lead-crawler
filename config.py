"""
CẤU HÌNH MẶC ĐỊNH — sửa ở đây rồi bấm Run main.py trong PyCharm.
Mọi giá trị đều có thể ghi đè bằng tham số dòng lệnh (xem: python main.py --help).
"""

# Khu vực cần quét: tên hiển thị -> các từ khóa không dấu để nhận diện tỉnh/thành trong địa chỉ.
CITIES = {
    "Hà Nội": ["ha-noi"],
    "TP. Hồ Chí Minh": ["ho-chi-minh", "tphcm", "tp-hcm"],
    "Đà Nẵng": ["da-nang"],
}

# ============================================================ NGUỒN TÌM CÔNG TY (đầu vào)

# File CSV danh sách công ty MKT có sẵn (tên / MST / website...). Để "" nếu không dùng.
# Mẫu: input_template.csv. Ví dụ: INPUT_FILE = "input_template.csv"
INPUT_FILE = ""

# Các nguồn tự tìm công ty, chạy theo thứ tự:
#   "doanhnghiep_me" : doanhnghiep.me theo tỉnh — có MST, SĐT, địa chỉ, ngành nghề chính, ngày thành lập
#                      (Hà Nội ~446 nghìn, TP.HCM ~833 nghìn, Đà Nẵng ~87 nghìn doanh nghiệp)
#   "tratencongty"   : tratencongty.com theo tỉnh — tên, người đại diện, địa chỉ (không có MST/SĐT)
# Cả hai đều xếp công ty mới thành lập lên trước.
DISCOVERY_SOURCES = ["doanhnghiep_me", "tratencongty"]

# --- doanhnghiep.me
# Phân trang của site bị lỗi (trang 2, 3... luôn hiện lại trang 1), nên tool đi theo địa bàn:
# trang tỉnh -> quận/huyện + phường/xã mới -> phường/xã thuộc quận. Mỗi trang địa bàn ~20 công ty khác nhau.
# Đây là số trang địa bàn tối đa mỗi tỉnh/thành. Hà Nội có khoảng 580 trang (~11.000 công ty).
# None = không giới hạn (đi hết mọi địa bàn). Số công ty ghi ra do MAX_COMPANIES quyết định.
DIRECTORY_MAX_PAGES_PER_CITY = None

# --- tratencongty.com
# Số trang tối đa mỗi tỉnh/thành (50 công ty/trang). None = không giới hạn;
# tool tự dừng khi gặp trang trống hoặc trang lặp lại nội dung.
REGISTRY_MAX_PAGES_PER_CITY = None

# Chỉ giữ công ty có tên / ngành nghề / lĩnh vực đoán chứa một trong các từ khóa (không phân biệt dấu).
# Áp dụng cho công ty tự tìm thấy (không lọc file đầu vào). Để trống = giữ tất cả.
# Ví dụ: ["xây dựng", "lập trình", "phần mềm", "logistics", "J620"]
KEYWORDS: list[str] = []

# ============================================================ NGUỒN BỔ SUNG (làm giàu dữ liệu)

# Bật/tắt từng nguồn (chạy theo đúng thứ tự dưới đây).
# VietQR (Cục Thuế): tên pháp lý chuẩn, tên tiếng Anh, địa chỉ đăng ký, trạng thái hoạt động (đang hoạt động / giải thể).
# Khi VietQR đã cho trạng thái, tool bỏ qua tratencongty cho công ty đó (đỡ 2 request x 3 giây).
USE_VIETQR_TAX_LOOKUP = True
# API miễn phí hay báo quá tải (429, bắt chờ vài phút).
#   True : chờ đúng thời gian VietQR yêu cầu rồi tra tiếp -> công ty nào cũng có dữ liệu VietQR, nhưng cả tool dừng
#          trong lúc chờ (hợp với chạy trên server, không vội).
#   False: tạm bỏ qua VietQR trong lúc bị giới hạn, các nguồn khác vẫn chạy -> nhanh hơn, một số công ty thiếu dữ liệu VietQR.
VIETQR_WAIT_IF_RATE_LIMITED = True
DOANHNGHIEP_ME_FETCH_DETAIL = True  # trang chi tiết doanhnghiep.me: người đại diện, tên viết tắt, ngành nghề đăng ký
# tratencongty.com: TRẠNG THÁI HOẠT ĐỘNG (thay VietQR, không bị giới hạn lượt), người đại diện, loại hình,
# ngày cấp phép, tên giao dịch, ngành nghề VSIC. Tra cả công ty đã đủ thông tin từ doanhnghiep.me nếu còn thiếu
# trạng thái, nên chậm hơn (~2 request x 3 giây/công ty). Công ty mới thành lập vài ngày có thể chưa có trên site này.
USE_TRATENCONGTY = True
TRATENCONGTY_FETCH_DETAIL = True    # đọc trang chi tiết tratencongty (trạng thái, ngành nghề nằm ở trang này)
TRATENCONGTY_SEARCH_BY_NAME = True  # công ty chưa có MST thì tra theo tên pháp lý (chỉ nhận khi khớp duy nhất)
ENRICH_FROM_WEBSITE = True          # website công ty: email, SĐT, lãnh đạo, MST, mạng xã hội, mô tả, nền tảng web

# ============================================================ CHUNG

# >>> GIÁ TRỊ DUY NHẤT CẦN CHỈNH <<<
# Dừng sau khi ghi được bấy nhiêu công ty. None = không giới hạn (chạy hết mọi nguồn).
# Các giới hạn khác trong file này đã để ở mức tối đa.
MAX_COMPANIES = None

# Giãn cách giữa các request tới cùng một site (giây). Đây không phải giới hạn số lượng;
# giảm xuống dễ bị site chặn (khi đó còn ra ít kết quả hơn), nên giữ nguyên.
VIETQR_DELAY_SECONDS = 2
DOANHNGHIEP_ME_DELAY_SECONDS = 2
TRATENCONGTY_DELAY_SECONDS = 3
WEBSITE_DELAY_SECONDS = 1.5
WEBSITE_MAX_PAGES = 10              # số trang con (liên hệ, giới thiệu, ban lãnh đạo...) đọc thêm ngoài trang chủ

REQUEST_TIMEOUT_SECONDS = 20
MAX_RETRIES = 3

# Tool khai báo trung thực là bot. Không đổi sang User-Agent giả trình duyệt để lách chặn.
USER_AGENT = "Mozilla/5.0 (compatible; MktLeadCrawler/1.0)"

# Thư mục ghi kết quả (tương đối so với thư mục dự án).
OUTPUT_DIR = "output"
