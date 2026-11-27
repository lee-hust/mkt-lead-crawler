# MKT Lead Crawler

Thu thập thông tin doanh nghiệp từ nhiều nguồn công khai. Mặc định quét **Hà Nội, TP. Hồ Chí Minh, Đà Nẵng**; chọn thêm được bất kỳ tỉnh nào trong **63 tỉnh/thành** (xem mục [Chọn tỉnh/thành](#chọn-tỉnhthành)). Tool gộp dữ liệu theo mã số thuế rồi xuất ra **CSV** (chỉ dữ liệu dạng chữ).

## Luồng xử lý

```
1. TÌM CÔNG TY (đầu vào)                     2. LÀM GIÀU DỮ LIỆU (theo thứ tự)                3. GỘP + GHI CSV
   File danh sách của MKT    ─┐                 VietQR / Cục Thuế (theo MST)                     gộp trùng theo
   doanhnghiep.me (theo tỉnh)─┼─> từng công ty ─> doanhnghiep.me chi tiết (người đại diện)  ──>   mã bản ghi / MST /
   tratencongty (theo tỉnh)  ─┘                 tratencongty (bù ngành nghề, loại hình)          tên + khu vực
                                                Website công ty (nếu có; có thể tìm ra MST
                                                  → tra lại VietQR + tratencongty)
```

## Nguồn dữ liệu

| Nguồn | Vai trò | Lấy được |
|---|---|---|
| **File đầu vào** (`input_template.csv`) | Danh sách MKT có sẵn | Tên, MST, website, email… do MKT cung cấp |
| **doanhnghiep.me** | Tìm công ty theo địa bàn: tỉnh → quận/huyện → phường/xã (Hà Nội khoảng 580 trang, ~11.000 công ty); bổ sung chi tiết | **Tên, MST, SĐT, địa chỉ, ngành nghề chính, ngày thành lập, phường/quận, người đại diện**, tên viết tắt, ngành nghề đăng ký |
| **VietQR** (dữ liệu Cục Thuế) | Tra theo MST | Tên pháp lý chuẩn, tên tiếng Anh, tên viết tắt, địa chỉ đăng ký thuế, **trạng thái hoạt động**. API miễn phí giới hạn lượt theo IP (hiện khoảng 1 lượt / phút), nên tool chạy 2 giai đoạn, có thể bật proxy miễn phí (xem mục [Tốc độ](#tốc-độ)) |
| **tratencongty.com** | Tìm theo tỉnh; tra theo MST/tên | **Trạng thái hoạt động** (khi VietQR không có), **người đại diện pháp luật**, loại hình DN, ngày cấp phép, ngày hoạt động, tên giao dịch, ngành nghề đăng ký (mã VSIC). Công ty mới thành lập vài ngày có thể chưa có trên site này |
| **Website của chính công ty** | Bổ sung (khi có website hoặc email tên miền riêng) | Email, SĐT, **lãnh đạo (họ tên + chức vụ)**, MST ở chân trang, Facebook/LinkedIn/YouTube/TikTok/Zalo, mô tả website, nền tảng web, có bản tiếng Anh, có trang tuyển dụng |

**Về phân trang của doanhnghiep.me:** chức năng phân trang của site đang lỗi (`/ha-noi/page2`, `/page50`… đều hiện lại trang 1, kể cả khi xem bằng Chrome). Vì vậy tool không lật trang, mà đi qua từng trang địa bàn; mỗi trang cho khoảng 20 công ty mới nhất của địa bàn đó.

Ngoài ra, tool tự **suy lĩnh vực từ tên công ty** (vd. "THỜI TRANG" → Dệt may - Thời trang) vào cột riêng. Cách này giúp phân nhóm cả những công ty mới chưa có ngành nghề trên trang nguồn.

Điều khoản của doanhnghiep.me yêu cầu ghi rõ nguồn. CSV đã có cột *Nguồn dữ liệu* và *Link doanhnghiep.me*; khi MKT dùng lại dữ liệu ra ngoài thì giữ ghi chú nguồn này.

## Kết quả

- `output/companies.csv`: mỗi dòng là một công ty (khoảng 46 cột).
- `output/contacts.csv`: mỗi dòng là một người liên hệ, gồm họ tên, chức vụ (Người đại diện pháp luật, Giám đốc…), SĐT, email, **nguồn + link nguồn** để kiểm chứng. Nối với file công ty qua cột *Mã bản ghi*.

File CSV dạng UTF-8 có BOM, mở thẳng bằng Excel không lỗi font. Khi code đổi bộ cột, file cũ được tự đổi tên (thêm ngày giờ) để giữ lại.

## Cài đặt bằng PyCharm

1. **File → Open** → chọn thư mục `D:\mkt-lead-crawler`.
2. Tạo môi trường ảo: **Settings → Project → Python Interpreter → Add Interpreter → Virtualenv** (Python 3.10 trở lên; đã kiểm tra với 3.14).
3. Mở Terminal trong PyCharm và chạy:
   ```bash
   pip install -r requirements.txt
   ```
4. Chuột phải `main.py` → **Run 'main'**.

## Chạy

**Lần đầu nên chạy thử nhỏ.** Trong `config.py`, đặt `MAX_COMPANIES = 20` rồi Run. Bỏ giới hạn thì đặt `None`.

Các cách dùng thường gặp. Trong PyCharm thì nhập tham số vào **Run → Edit Configurations → Parameters**.

Chỉ Hà Nội, 50 công ty:

```bash
python main.py --cities "Hà Nội" --max-companies 50
```

### Chọn tỉnh/thành

Sửa `SELECTED_CITIES` trong `config.py`, chép đúng tên (có dấu) từ `ALL_CITIES` ngay bên dưới:

```python
SELECTED_CITIES = ["Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Bình Dương"]
SELECTED_CITIES = ["all"]   # cả 63 tỉnh/thành
```

Hoặc truyền tham số (ghi đè `config.py`):

```bash
python main.py --cities "Hải Phòng" "Bình Dương"
python main.py --cities all
```

- doanhnghiep.me và tratencongty.com vẫn chia theo **63 tỉnh/thành cũ** (trước sáp nhập còn 34 tỉnh/thành từ 7/2025), nên danh sách vẫn có Bình Dương, Hà Nam, Quảng Nam... Cột "Khu vực quét" ghi theo tên cũ này; địa chỉ của công ty đã cập nhật sau sáp nhập có thể ghi tên tỉnh mới.
- Tool quét lần lượt từng tỉnh theo thứ tự trong danh sách, xong tỉnh này mới sang tỉnh sau. Muốn có ngay dữ liệu tỉnh nào thì đặt tỉnh đó lên đầu.
- Thêm tỉnh khi chạy lại không làm mất dữ liệu cũ: công ty đã có trong `companies.csv` được bỏ qua.

Lọc theo ngành nghề (so với tên, ngành nghề, lĩnh vực đoán; không phân biệt dấu):

```bash
python main.py --keywords "xây dựng" "lập trình" "logistics"
```

Giới hạn số trang địa bàn đọc ở mỗi tỉnh (mỗi trang khoảng 20 công ty):

```bash
python main.py --directory-pages 100
```

Chỉ làm giàu danh sách MKT có sẵn, không tự tìm thêm:

```bash
python main.py --input danh_sach.csv --sources
```

Chạy nhanh, bớt nguồn bổ sung:

```bash
python main.py --no-registry --no-website
```

**Từ khóa:** nên dùng từ ngữ theo tên ngành VSIC (vd. "lập trình" thay vì "phần mềm"), mã ngành (vd. "J620"), hoặc tên lĩnh vực trong cột *Lĩnh vực (suy từ tên)* (vd. "Công nghệ", "Logistics").

**File đầu vào:** copy `input_template.csv` rồi điền danh sách. Chỉ cần cột *Tên công ty* hoặc *Mã số thuế*; có MST thì kết quả chính xác hơn nhiều. Nếu sửa bằng Excel, nên lưu dạng **CSV UTF-8**.

## Tốc độ

Mỗi site có khoảng nghỉ riêng: doanhnghiep.me và VietQR 2 giây, tratencongty 3 giây, website 1,5 giây. Khi bị báo quá tải (429), nguồn bổ sung được tạm bỏ qua đến hết thời gian site yêu cầu chờ, các nguồn khác vẫn chạy. Mỗi công ty tốn khoảng 2–8 giây tùy số nguồn có dữ liệu, tức khoảng **500–1.500 công ty/giờ**. Có thể để máy chạy qua đêm. Muốn nhanh hơn thì tắt bớt nguồn bổ sung (`--no-registry`, `--no-website`, `--no-directory-detail`). Không nên giảm khoảng nghỉ, vì dễ bị chặn.

**VietQR chạy 2 giai đoạn** (mặc định). VietQR miễn phí giới hạn lượt theo IP: trước đây khoảng 25 lượt / 10 phút (~150 công ty/giờ), từ 27/11/2026 Cloudflare đứng trước VietQR chỉ cho khoảng 1 lượt / phút (~60 công ty/giờ), chậm hơn hẳn các nguồn khác:

| | Làm gì | Cấu hình |
|---|---|---|
| **Giai đoạn 1** | Cào mọi nguồn. VietQR còn lượt thì tra, hết lượt thì bỏ qua công ty đó cho nhanh (trạng thái hoạt động lấy tạm từ tratencongty). MKT sớm có SĐT, người đại diện... của mọi công ty | `VIETQR_WAIT_IF_RATE_LIMITED = False` |
| **Giai đoạn 2** | Cào xong, tool tự tra bù VietQR cho công ty có MST mà chưa có "VietQR (Cục Thuế)" trong cột "Nguồn dữ liệu". Chờ đúng thời gian VietQR yêu cầu, cập nhật thẳng vào `companies.csv` (lưu khoảng 10 phút/lần) | `VIETQR_BACKFILL_AFTER_CRAWL = True` |

- Chạy riêng giai đoạn 2 (vd. sau khi dừng giữa chừng): `python main.py --vietqr-backfill`. Dừng lúc nào cũng được, chạy lại sẽ tra tiếp phần còn thiếu.
- Tiến độ giai đoạn 2 được in 5 phút một lần (dòng `Giai đoạn 2 - tiến độ: ...`): số công ty đã tra, tốc độ thực tế trung bình 15 phút gần nhất, thời gian còn lại và giờ dự kiến xong. Trên server: `docker logs mkt-crawler 2>&1 | grep "tiến độ" | tail -1`.
- Cào xong thì dừng, không tra bù: `--no-vietqr-backfill`.
- Chạy 1 giai đoạn như cũ (tra VietQR xong mới làm tiếp, cả tool đứng chờ khi hết lượt): `VIETQR_WAIT_IF_RATE_LIMITED = True`.
- Trong lúc giai đoạn 2 chạy, tool đang giữ file nên không chạy giai đoạn 1 song song được (tool tự thoát với mã 2).

**Tra VietQR qua proxy miễn phí (tùy chọn, mặc định tắt).** Bật bằng `--vietqr-free-proxies` (hoặc `VIETQR_FREE_PROXIES = True`):

```bash
python main.py --vietqr-backfill --vietqr-free-proxies
```

- Tool dùng thư viện [swiftshadow](https://github.com/sachin-sankar/swiftshadow) lấy proxy miễn phí từ các danh sách công khai (ProxyScrape, monosans, TheSpeedX, proxydb.net...), thử từng proxy với một trang HTTPS (api.ipify.org), rồi tra VietQR xoay vòng qua các proxy mở được HTTPS, cùng IP của máy chạy tool. Mỗi IP được khoảng 1 lượt / phút, nên có N proxy dùng được thì nhanh hơn khoảng N lần.
- Việc lấy proxy chạy ở nền, tối đa 10 phút / lần. Trong lúc chờ, VietQR vẫn tra bằng IP máy chạy tool. Còn dưới 10 proxy dùng được thì tool tự lấy thêm.
- Proxy lỗi kết nối 2 lần liên tiếp, đòi tài khoản hoặc bị VietQR trả 403 thì bị bỏ. IP máy chạy tool bị 403 mà còn proxy thì tool bỏ IP đó và tra tiếp bằng proxy.
- Chỉ VietQR đi qua proxy; doanhnghiep.me, tratencongty, website công ty vẫn gọi trực tiếp.
- Log có các dòng `swiftshadow: lấy được ... proxy`, `api.vietqr.io: thêm N proxy`, `bỏ proxy ...`.
- **Rủi ro:** proxy miễn phí không rõ chủ (có thể là máy cấu hình sai hoặc bị chiếm quyền), hay chết, có thể đã bị VietQR chặn sẵn. VietQR chạy HTTPS nên proxy không đọc hay sửa được dữ liệu tra cứu. Nên hỏi IT trước khi bật trên server công ty. swiftshadow dùng giấy phép GPL-3.0, chỉ dùng nội bộ thì không ảnh hưởng.

## Dừng và chạy tiếp

- Mỗi công ty được ghi ngay sau khi xử lý xong. Muốn dừng thì bấm **Stop** hoặc Ctrl+C.
- Chạy lại thì tool tự **bỏ qua công ty đã có** (theo mã bản ghi, MST, tên + khu vực).
- Muốn bắt đầu lại từ đầu: xóa thư mục `output`.
- Nhật ký chạy nằm ở `output/crawl.log`.

## Chạy trên server

Chỉ cần upload các file sau:

| Cần | Không cần (để lại máy local) |
|---|---|
| `main.py`, `config.py`, `requirements.txt`, thư mục `lead_crawler/` | `.idea/` (của PyCharm), `.venv/`, `output/`, `__pycache__/` |
| `Dockerfile`, `.dockerignore` (chỉ khi dùng Docker) | `README.md`, `input_template.csv` (tùy) |
| File danh sách đầu vào (nếu dùng `--input`) | |

Trên server, tool tự xử lý mấy việc sau:

- **Không chạy chồng:** tool dùng khóa `output/.run.lock`; nếu lần trước chưa xong thì lần mới tự thoát với mã 2.
- **Dừng an toàn:** `systemctl stop`, `docker stop` hay `kill` đều dừng như Ctrl+C.
- **Log tự xoay vòng:** tối đa 5 file x 10 MB.
- **Mã thoát:** 0 là xong, 2 là đang có lần chạy khác, 130 là bị dừng.

**Cách 1: Python trực tiếp (Ubuntu/Debian).** Upload code vào ví dụ `/opt/mkt-lead-crawler`, rồi chạy lần lượt:

```bash
sudo apt install -y python3 python3-venv
```

```bash
cd /opt/mkt-lead-crawler && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python main.py --max-companies 20
```

Chạy nền lâu dài (theo dõi bằng `tail -f output/crawl.log`):

```bash
nohup .venv/bin/python main.py > /dev/null 2>&1 &
```

Chạy tự động hằng đêm lúc 1 giờ sáng để lấy công ty mới thành lập. Thêm dòng sau bằng `crontab -e`:

```
0 1 * * * cd /opt/mkt-lead-crawler && .venv/bin/python main.py > /dev/null 2>&1
```

**Cách 2: Docker.**

```bash
docker build -t mkt-lead-crawler .
```

```bash
docker run --rm -v "$(pwd)/output:/app/output" mkt-lead-crawler --max-companies 20
```

Với Docker:

- Sửa `config.py` thì build lại image, hoặc gắn từ ngoài vào bằng `-v "$(pwd)/config.py:/app/config.py"`.
- Dùng file đầu vào thì gắn thêm `-v "$(pwd)/input:/app/input"` và truyền `--input input/danh_sach.csv`.

**Lấy kết quả về máy:** dùng WinSCP hoặc FileZilla (SFTP), hoặc lệnh:

```bash
scp user@IP_SERVER:/opt/mkt-lead-crawler/output/*.csv .
```

## Lưu ý về mạng

Kết quả kiểm tra truy cập từ wifi công ty (20/11/2026):

| Trang | Kết quả | Nguyên nhân |
|---|---|---|
| doanhnghiep.me, tratencongty.com, api.vietqr.io | Vào được | — các nguồn tool đang dùng đều chạy được trên mạng công ty |
| thongtindoanhnghiep.co, vinabiz.org | Bị ngắt khi bắt tay mã hóa (TLS) | Dấu hiệu **tường lửa mạng công ty** chặn theo tên miền |
| overpass-api.de (OpenStreetMap) | Lỗi chứng chỉ | Dấu hiệu **proxy mạng công ty** can thiệp kết nối |
| hosocongty.vn, masocongty.vn | Không phân giải được tên miền (kể cả qua DNS 8.8.8.8) | Mạng chặn DNS, hoặc site đã ngừng hoạt động |
| trangvangvietnam.com, masothue.com | 403 Cloudflare | **Site chặn bot**, không phải do mạng; đổi mạng không giải quyết được |
| overpass.kumi.systems | Vào được | Bản sao dự phòng của OpenStreetMap |

- Trang bị **mạng** chặn (tường lửa, proxy, DNS) có thể vào được khi chạy trên server hoặc ở mạng khác. Trang bị **site** chặn bot thì ở đâu cũng bị.
- Không tự dùng VPN/proxy để vượt tường lửa công ty khi chưa được IT cho phép.
- Khi đưa lên server, nếu thongtindoanhnghiep.co hoặc vinabiz.org vào được thì cần kiểm tra robots.txt và điều khoản sử dụng trước khi thêm làm nguồn.

## Thêm nguồn khác

1. Tạo file trong `lead_crawler/sources/`, kế thừa `EnrichmentSource` và viết `enrich(company)`. Hàm này điền trường còn trống bằng `company.set_if_empty(...)` và trả về danh sách `ContactPerson`. Đặt `uses_tax_code = True` nếu nguồn tra theo MST.
2. Đăng ký nguồn trong `build_enrichment_sources()` ở `lead_crawler/pipeline.py`. Nếu nguồn còn dùng để tìm công ty thì thêm vào `iter_discovered_companies()`.

## Nguồn đã thử và không dùng

| Nguồn | Lý do |
|---|---|
| Trang Vàng (trangvangvietnam.com) và trang chị em yellowpages.com.vn / .vn | Cloudflare chặn bot (403); lấy qua trang chị em cùng chủ quản là lách lệnh chặn |
| masothue.com, dnb.com, kompass.com, topcv.vn | Chặn bot / CAPTCHA |
| infodoanhnghiep.com | Điều khoản cấm crawler cho mục đích thương mại |
| hosocongty.vn, masocongty.vn, thongtindoanhnghiep.co, vinabiz.org | Không vào được từ mạng công ty (xem mục *Lưu ý về mạng*); chưa đánh giá được điều khoản |
| OpenStreetMap (Overpass API) | Máy chủ chính bị proxy mạng công ty can thiệp; dữ liệu doanh nghiệp ở Việt Nam ít |

Tool cố ý **không** vượt Cloudflare/CAPTCHA, không giả trình duyệt, không đọc dữ liệu site cố ý ẩn (email mã hóa, MST/SĐT dạng ảnh), không đoán email theo tên người, không cào LinkedIn/Facebook cá nhân. Tool luôn tuân thủ `robots.txt` và giãn cách request. Ngoại lệ duy nhất: khi bật `--vietqr-free-proxies`, tool xoay IP qua proxy miễn phí để vượt giới hạn lượt theo IP của VietQR. Mỗi proxy vẫn giữ khoảng nghỉ riêng, và proxy nào bị chặn (403) thì bị bỏ.

## Lưu ý khi dùng dữ liệu

Tên, SĐT, email của **người liên hệ** (kể cả người đại diện pháp luật) là dữ liệu cá nhân theo Nghị định 13/2023/NĐ-CP và Luật Bảo vệ dữ liệu cá nhân 2025 (hiệu lực từ 01/01/2026).

- Chỉ dùng nội bộ để liên hệ công việc; không bán hoặc chia sẻ danh sách ra ngoài.
- Gọi điện, nhắn tin, gửi email quảng cáo phải tuân thủ quy định chống tin nhắn rác, cuộc gọi rác (Nghị định 91/2020/NĐ-CP). Người nhận yêu cầu ngừng liên hệ thì phải xóa họ khỏi danh sách.
- CSV chứa dữ liệu cá nhân, nên **không** để thư mục `output/` truy cập công khai qua web.

Nên hỏi bộ phận pháp chế/compliance trước khi dùng dữ liệu cho chiến dịch lớn.
