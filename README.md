# MKT Lead Crawler

Thu thập thông tin doanh nghiệp từ nguồn công khai theo tỉnh/thành **địa giới mới** (sau sáp nhập 7/2025; hiện cấu hình 5 thành phố: Hà Nội, TP. Hồ Chí Minh, Cần Thơ, Đà Nẵng, Hải Phòng), gộp theo mã số thuế, xuất ra CSV.

## Nguồn dữ liệu

| Nguồn | Dùng để | Lấy được |
|---|---|---|
| File đầu vào (`input_template.csv`) | Danh sách MKT có sẵn | Tên, MST, website... |
| VietQR (Cục Thuế) | Tra theo MST, **mặc định tắt** (bật bằng `--vietqr`) | Tên pháp lý, tên tiếng Anh, địa chỉ đăng ký, trạng thái. Giới hạn ~1 lượt / phút mỗi IP; API miễn phí dừng 31/12/2026 |
| infodoanhnghiep.com | **Tìm công ty theo tỉnh mới** (công ty mới lên trước) + tra theo MST | Tên, MST, địa chỉ, ngày cấp; trạng thái người nộp thuế, cơ quan thuế, số lao động, ngành nghề VSIC, số chi nhánh |
| doanhnghiep.biz | Tra theo MST (mở thẳng trang `/<MST>`, 1 request mỗi công ty) | **Số điện thoại** (dạng chữ), người đại diện, tình trạng, loại hình. Email trên site bị Cloudflare mã hóa nên không lấy |
| tratencongty.com | Tìm theo tỉnh; tra theo MST / tên | Người đại diện, loại hình, trạng thái, ngành nghề |
| Website công ty | Khi có website | Email, SĐT, lãnh đạo, MST |

Thứ tự bổ sung: infodoanhnghiep → doanhnghiep.biz → tratencongty → website (bật VietQR thì VietQR đứng đầu). Trạng thái người nộp thuế lấy từ infodoanhnghiep (đã đối chiếu với Cơ quan thuế) nên không cần VietQR. Cột *Link doanhnghiep.me* giữ lại cho cùng bộ cột với file cũ (nguồn này đã bỏ nên file mới để trống).

## Kết quả

- `output/companies.csv`: mỗi dòng một công ty (37 cột).
- Người liên hệ gộp trong cột *Liên hệ & chức vụ* (vd. `Người đại diện pháp luật: Nguyễn Văn A`). Cần mỗi dòng một người thì bật `--contacts-file` (hoặc `WRITE_CONTACTS_FILE = True`) để ghi thêm `output/contacts.csv`, nối với công ty qua *Mã bản ghi*.
- `output/crawl.log`: nhật ký chạy.

File là UTF-8 có BOM, mở thẳng bằng Excel. Khi bản mới thêm / bỏ cột, file cũ tự được nâng cấp lúc chạy (giữ dữ liệu theo tên cột, bản gốc lưu thành `companies_truoc_nang_cap_<thời gian>.csv`).

## Dữ liệu cũ (trên server)

File cũ (lấy từ doanhnghiep.me, 37 cột như file mới) nằm ở `/opt/mkt-lead-crawler/output_cu`; tool không đọc lại, file mới cào lại từ đầu. Tải file cũ về:

```bash
scp root@IP_SERVER:/opt/mkt-lead-crawler/output_cu/companies.csv root@IP_SERVER:/opt/mkt-lead-crawler/output_cu/contacts.csv /d/mkt-lead-crawler/output_cu/
```

## Tỉnh/thành

Cấu hình trong `config.py`: `SELECTED_CITIES` (tỉnh cần quét) và `ALL_CITIES` (mỗi tỉnh mới: đường dẫn trên infodoanhnghiep.com, số trang tối đa `pages`, từ khóa các tỉnh cũ gộp vào). Thêm tỉnh thì thêm một dòng vào `ALL_CITIES`, vd. `"Huế": {"infodoanhnghiep": "Hue", "pages": 300, "keys": ["thua-thien-hue", "hue"]}`.

| Thành phố mới | Gồm tỉnh cũ | Trang trên infodoanhnghiep (27/11/2026) | Quét (`pages`) | ~ Số công ty |
|---|---|---|---|---|
| Hà Nội | Hà Nội | 17.025 | 1.500 | 30.000 |
| TP. Hồ Chí Minh | TP. Hồ Chí Minh, Bình Dương, Bà Rịa - Vũng Tàu | 32.305 | 2.000 | 40.000 |
| Cần Thơ | Cần Thơ, Sóc Trăng, Hậu Giang | 1.916 | 400 | 8.000 |
| Đà Nẵng | Đà Nẵng, Quảng Nam | 3.455 | 550 | 11.000 |
| Hải Phòng | Hải Phòng, Hải Dương | 3.769 | 550 | 11.000 |

Mỗi trang 20 công ty, mới thành lập lên trước. Các thành phố được quét xen kẽ từng trang (trang 1 cả 5 thành phố, rồi trang 2...) nên dừng lúc nào file cũng có đủ 5 thành phố; thành phố nào đủ số trang thì dừng, các thành phố còn lại chạy tiếp. `--directory-pages N` đặt cùng N trang cho mọi thành phố (thay số trong `pages`).

Giai đoạn 2 tự đổi tên tỉnh cũ trong dữ liệu đã có sang tỉnh mới (vd. Bình Dương → TP. Hồ Chí Minh) ở cột *Khu vực quét* và *Tỉnh/TP*.

## Cài đặt và chạy (PyCharm)

1. Mở thư mục `D:\mkt-lead-crawler`, tạo Virtualenv (Python 3.10+), chạy `pip install -r requirements.txt`.
2. Sửa `config.py` (tỉnh cần quét, giới hạn số công ty...), rồi Run `main.py`.

Ví dụ dòng lệnh (`python main.py --help` để xem đủ):

```bash
python main.py --cities "Hà Nội" --max-companies 50
python main.py --cities "Cần Thơ" "Đà Nẵng"
python main.py --keywords "xây dựng" "logistics"
python main.py --input danh_sach.csv --sources
python main.py --vietqr-backfill
```

Dừng lúc nào cũng được (Stop / Ctrl+C); chạy lại thì bỏ qua công ty đã có và đọc tiếp danh sách infodoanhnghiep sau trang đã xong (lưu ở `output/tien_do_infodoanhnghiep.json`). Xóa file đó để quét lại từ trang 1 (lấy công ty mới thành lập). Muốn làm lại từ đầu thì xóa thư mục `output`.

## Hai giai đoạn

| | Làm gì |
|---|---|
| Giai đoạn 1 | Cào mọi nguồn; site nào báo hết lượt thì bỏ qua cho nhanh |
| Giai đoạn 2 | Tra bù công ty chưa có dữ liệu thuế (infodoanhnghiep; VietQR nếu bật) hoặc chưa có số điện thoại (doanhnghiep.biz). Không tra lại công ty đã đủ chỉ để lấy số lao động / cơ quan thuế. Lưu file 10 phút / lần |

- Chỉ chạy giai đoạn 2: `--vietqr-backfill`. Cào xong không tra bù: `--no-vietqr-backfill`.
- Tiến độ in 5 phút / lần (tốc độ thực tế, giờ dự kiến xong): `grep "tiến độ" output/crawl.log`.
- `--vietqr-free-proxies` (cùng `--vietqr`): xoay vòng VietQR qua proxy miễn phí (thư viện swiftshadow). Proxy miễn phí không rõ chủ, hay chết; nên hỏi IT trước khi bật.
- `--no-infodoanhnghiep`, `--no-doanhnghiep-biz`: không dùng nguồn đó.

## Chạy trên server (Docker)

`chay_tren_server.sh` chứa sẵn code (đã nén). Chép lên server rồi chạy, script sẽ giải nén vào `/opt/mkt-lead-crawler`, build image và chạy nền:

```bash
scp /d/mkt-lead-crawler/chay_tren_server.sh root@IP_SERVER:/root/
```

```bash
bash /root/chay_tren_server.sh
```

Thêm tham số sau tên script để bản mới chạy luôn với tham số đó, vd. `bash /root/chay_tren_server.sh --vietqr-backfill`. Script dừng container cũ an toàn (`docker stop -t 60`) sau khi build xong; build lỗi thì giữ nguyên container đang chạy.

Đổi tham số mà không deploy lại (vd. chỉ giai đoạn 2):

```bash
docker stop -t 60 mkt-crawler; docker rm mkt-crawler; docker run -d --name mkt-crawler -v /opt/mkt-lead-crawler/output:/app/output mkt-lead-crawler --vietqr-backfill --vietqr-free-proxies
```

Xem log: `docker logs --tail 20 mkt-crawler`. Lấy kết quả về máy:

```bash
scp root@IP_SERVER:/opt/mkt-lead-crawler/output/companies.csv /d/mkt-lead-crawler/output_server/
```

Tool tự khóa thư mục output (không chạy chồng), dừng an toàn khi `docker stop`, log tự xoay vòng (5 file x 10 MB).

## Nguyên tắc thu thập

- Tuân thủ `robots.txt`, giãn cách request, khai báo đúng là bot. Không vượt Cloudflare / CAPTCHA, không đọc dữ liệu site cố ý ẩn (SĐT dạng ảnh trên tratencongty, email mã hóa trên doanhnghiep.biz), không đoán email.
- Ngoại lệ: `--vietqr-free-proxies` xoay IP để vượt giới hạn lượt của VietQR. infodoanhnghiep.com có điều khoản cấm thu thập tự động cho mục đích thương mại.
- Không dùng: Trang Vàng, masothue.com, dnb.com, kompass.com, topcv.vn (chặn bot / CAPTCHA); hosocongty.vn, masocongty.vn, thongtindoanhnghiep.co, vinabiz.org (không vào được từ mạng công ty).
- Dữ liệu cũ từ doanhnghiep.me: site yêu cầu ghi nguồn, giữ cột *Nguồn dữ liệu* khi dùng lại.

## Dữ liệu cá nhân

Tên, SĐT, email của người liên hệ là dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP, Luật Bảo vệ dữ liệu cá nhân 2025). Chỉ dùng nội bộ, không chia sẻ ra ngoài, tuân thủ quy định chống tin nhắn / cuộc gọi rác (Nghị định 91/2020/NĐ-CP), xóa người đã yêu cầu ngừng liên hệ. Không để thư mục `output/` truy cập công khai. Hỏi pháp chế trước khi dùng cho chiến dịch lớn.

## Thêm nguồn

Tạo file trong `lead_crawler/sources/` kế thừa `EnrichmentSource` (viết `enrich(company)`), rồi đăng ký trong `build_enrichment_sources()` ở `lead_crawler/pipeline.py`.
