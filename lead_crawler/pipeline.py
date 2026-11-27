"""
Luồng chính: tìm công ty -> lần lượt các nguồn bổ sung -> gộp trùng, ghi CSV.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterator, Optional

from lead_crawler.http_client import HttpClient
from lead_crawler.industry_guess import guess_industry, guess_industry_from_texts, infer_legal_form
from lead_crawler.models import Company, ContactPerson
from lead_crawler.sources.base import EnrichmentSource
from lead_crawler.sources.company_website import CompanyWebsiteSource
from lead_crawler.sources.doanhnghiep_biz import DoanhNghiepBizSource
from lead_crawler.sources.infodoanhnghiep import PROGRESS_FILE_NAME as INFODOANHNGHIEP_PROGRESS_FILE_NAME
from lead_crawler.sources.infodoanhnghiep import InfoDoanhNghiepSource
from lead_crawler.sources.input_file import read_input_companies
from lead_crawler.sources.tratencongty import TraTenCongTySource
from lead_crawler.free_proxies import FreeProxyPool
from lead_crawler.sources.vietqr import API_HOST as VIETQR_API_HOST
from lead_crawler.sources.vietqr import VietQrSource
from lead_crawler.storage import CsvStore
from lead_crawler.text_utils import to_ascii_key

logger = logging.getLogger(__name__)

DISCOVERY_INFODOANHNGHIEP = "infodoanhnghiep"
DISCOVERY_TRATENCONGTY = "tratencongty"
ALL_DISCOVERY_SOURCES = [DISCOVERY_INFODOANHNGHIEP, DISCOVERY_TRATENCONGTY]


@dataclass
class Settings:
    """
    Toàn bộ tham số của một lần chạy (lấy từ config.py, ghi đè bằng tham số dòng lệnh).
    """

    cities: dict[str, list[str]]
    # Đường dẫn tỉnh trên infodoanhnghiep.com (vd. "Ha-Noi") và từ khóa của mọi tỉnh trong config (đổi tên tỉnh cũ).
    infodoanhnghiep_paths: dict[str, str] = field(default_factory=dict)
    all_cities: dict[str, list[str]] = field(default_factory=dict)
    discovery_sources: list[str] = field(default_factory=lambda: list(ALL_DISCOVERY_SOURCES))
    input_file: Optional[Path] = None
    directory_max_pages_per_city: Optional[int] = None
    # Số trang infodoanhnghiep riêng từng tỉnh (config.ALL_CITIES "pages"); tỉnh không có thì dùng giá trị trên.
    directory_pages_by_city: dict[str, int] = field(default_factory=dict)
    registry_max_pages_per_city: Optional[int] = None
    keywords: list[str] = field(default_factory=list)
    max_companies: Optional[int] = None
    use_vietqr_tax_lookup: bool = False
    vietqr_wait_if_rate_limited: bool = False
    # Tra VietQR xoay vòng qua proxy miễn phí (lấy bằng swiftshadow), bên cạnh IP máy chạy tool.
    vietqr_free_proxies: bool = False
    vietqr_free_proxy_max: int = 100
    vietqr_free_proxy_min: int = 10
    vietqr_free_proxy_refresh_minutes: int = 10
    # infodoanhnghiep.com: dữ liệu đăng ký thuế theo MST (thay VietQR khi hết lượt), số lao động, cơ quan thuế...
    use_infodoanhnghiep: bool = True
    infodoanhnghiep_delay_seconds: float = 2
    # doanhnghiep.biz: số điện thoại dạng chữ, người đại diện, tình trạng.
    use_doanhnghiep_biz: bool = True
    doanhnghiep_biz_delay_seconds: float = 2
    use_tratencongty: bool = True
    tratencongty_fetch_detail: bool = True
    tratencongty_search_by_name: bool = True
    enrich_from_website: bool = True
    vietqr_delay_seconds: float = 2
    tratencongty_delay_seconds: float = 3
    website_delay_seconds: float = 1.5
    website_max_pages: int = 10
    request_timeout_seconds: float = 20
    max_retries: int = 3
    user_agent: str = "Mozilla/5.0 (compatible; MktLeadCrawler/1.0)"
    output_dir: Path = Path("output")


def build_http_client(settings: Settings) -> HttpClient:
    """
    Tạo HttpClient dùng chung cho mọi nguồn; bật proxy miễn phí thì VietQR gọi xoay vòng qua các proxy đó.
    """
    http_client = HttpClient(
        user_agent=settings.user_agent,
        default_delay_seconds=settings.website_delay_seconds,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
    )
    if settings.use_vietqr_tax_lookup and settings.vietqr_free_proxies:
        free_proxy_pool = FreeProxyPool(
            cache_folder=settings.output_dir / ".swiftshadow",
            max_proxies=settings.vietqr_free_proxy_max,
            refresh_seconds=settings.vietqr_free_proxy_refresh_minutes * 60,
        )
        http_client.set_proxy_supplier(
            VIETQR_API_HOST,
            free_proxy_pool.take_new_proxies,
            settings.vietqr_free_proxy_min,
        )
        free_proxy_pool.start_fetch()
        logger.info(
            "VietQR: bật proxy miễn phí (swiftshadow), đang lấy proxy ở nền; còn dưới %d proxy dùng được "
            "thì lấy thêm (tối đa %d phút / lần)",
            settings.vietqr_free_proxy_min,
            settings.vietqr_free_proxy_refresh_minutes,
        )

    return http_client


def build_enrichment_sources(
    settings: Settings,
    http_client: HttpClient,
    tra_ten_cong_ty_source: TraTenCongTySource,
) -> list[EnrichmentSource]:
    """
    Nguồn bổ sung theo thứ tự: VietQR -> infodoanhnghiep -> doanhnghiep.biz -> tratencongty -> website.
    """
    enrichment_sources: list[EnrichmentSource] = []
    if settings.use_vietqr_tax_lookup:
        enrichment_sources.append(
            VietQrSource(
                http_client,
                settings.vietqr_delay_seconds,
                settings.vietqr_wait_if_rate_limited,
            )
        )

    if settings.use_infodoanhnghiep:
        enrichment_sources.append(
            InfoDoanhNghiepSource(
                http_client,
                settings.infodoanhnghiep_delay_seconds,
                False,
            )
        )

    if settings.use_doanhnghiep_biz:
        enrichment_sources.append(
            DoanhNghiepBizSource(
                http_client,
                settings.doanhnghiep_biz_delay_seconds,
                False,
            )
        )

    if settings.use_tratencongty:
        enrichment_sources.append(tra_ten_cong_ty_source)

    if settings.enrich_from_website:
        enrichment_sources.append(
            CompanyWebsiteSource(
                http_client,
                settings.website_delay_seconds,
                settings.website_max_pages,
            )
        )

    return enrichment_sources


# ---------------------------------------------------------------------- tìm công ty


def iter_discovered_companies(
    settings: Settings,
    info_doanh_nghiep_source: InfoDoanhNghiepSource,
    tra_ten_cong_ty_source: TraTenCongTySource,
) -> Iterator[Company]:
    """
    Nối các nguồn đầu vào: file MKT -> infodoanhnghiep -> tratencongty; nguồn lỗi thì bỏ qua.
    """
    if settings.input_file:
        logger.info("=== Nguồn đầu vào: file %s", settings.input_file)
        yield from read_input_companies(
            settings.input_file,
            settings.cities,
        )

    if DISCOVERY_INFODOANHNGHIEP in settings.discovery_sources:
        logger.info("=== Nguồn đầu vào: infodoanhnghiep.com (danh sách theo tỉnh, địa giới mới, xen kẽ từng trang)")
        yield from info_doanh_nghiep_source.iter_companies(
            settings.cities,
            settings.infodoanhnghiep_paths,
            settings.directory_max_pages_per_city,
            settings.output_dir / INFODOANHNGHIEP_PROGRESS_FILE_NAME,
            settings.directory_pages_by_city,
        )

    if DISCOVERY_TRATENCONGTY in settings.discovery_sources:
        logger.info("=== Nguồn đầu vào: tratencongty.com (danh sách theo tỉnh)")
        yield from tra_ten_cong_ty_source.iter_companies(
            settings.cities,
            settings.registry_max_pages_per_city,
        )


# ---------------------------------------------------------------------- làm giàu dữ liệu


def finalize_contacts(
    company: Company,
    contact_persons: list[ContactPerson],
) -> list[ContactPerson]:
    """
    Điền thông tin công ty vào từng người liên hệ và gộp người trùng (cùng tên + chức vụ) giữa các nguồn.
    """
    merged_contacts: dict[tuple[str, str], ContactPerson] = {}
    for contact_person in contact_persons:
        contact_person.record_id = company.record_id
        contact_person.tax_code = company.tax_code
        contact_person.company_name = company.company_name
        contact_person.target_city = company.target_city
        key = (to_ascii_key(contact_person.full_name), to_ascii_key(contact_person.position))
        existing_contact = merged_contacts.get(key)
        if existing_contact is None:
            merged_contacts[key] = contact_person
            continue

        existing_contact.phone = existing_contact.phone or contact_person.phone
        existing_contact.email = existing_contact.email or contact_person.email
        if contact_person.source not in existing_contact.source:
            existing_contact.source = f"{existing_contact.source}; {contact_person.source}"

    final_contacts = list(merged_contacts.values())
    company.contacts_summary = summarize_contacts(final_contacts)
    company.contact_count = str(len(final_contacts))

    return final_contacts


def summarize_contacts(contact_persons: list[ContactPerson]) -> str:
    """
    Gộp người liên hệ thành một ô, vd. "Người đại diện pháp luật: ... | Kế toán trưởng: ...".
    """
    parts = []
    for contact_person in contact_persons:
        label = f"{contact_person.position}: {contact_person.full_name}" if contact_person.position else contact_person.full_name
        reachable = ", ".join(value for value in (contact_person.phone, contact_person.email) if value)
        parts.append(f"{label} ({reachable})" if reachable else label)

    return " | ".join(part for part in parts if part)


def run_source_safely(
    enrichment_source: EnrichmentSource,
    company: Company,
) -> list[ContactPerson]:
    """
    Chạy một nguồn; nguồn lỗi thì ghi log và bỏ qua, không làm dừng cả chương trình.
    """
    try:
        return enrichment_source.enrich(company)
    except Exception:
        logger.exception("Nguồn %s lỗi với %s", enrichment_source.name, company.company_name)

        return []


def enrich_company(
    company: Company,
    enrichment_sources: list[EnrichmentSource],
) -> list[ContactPerson]:
    """
    Chạy lần lượt các nguồn bổ sung; MST tìm ra muộn thì chạy lại các nguồn tra theo MST.
    """
    contact_persons: list[ContactPerson] = []
    tax_code_at_run: dict[int, str] = {}
    for enrichment_source in enrichment_sources:
        tax_code_at_run[id(enrichment_source)] = company.tax_code
        contact_persons.extend(
            run_source_safely(
                enrichment_source,
                company,
            )
        )

    for enrichment_source in enrichment_sources:
        missed_tax_code = not tax_code_at_run[id(enrichment_source)]
        if enrichment_source.uses_tax_code and company.tax_code and missed_tax_code:
            logger.info("  Có MST %s từ %s, tra lại ở %s", company.tax_code, company.tax_code_source, enrichment_source.name)
            contact_persons.extend(
                run_source_safely(
                    enrichment_source,
                    company,
                )
            )

    fill_derived_fields(company)

    return contact_persons


def fill_derived_fields(company: Company) -> None:
    """
    Tính trường suy ra: lĩnh vực đoán, loại hình, năm thành lập, số năm hoạt động.
    """
    # Không dùng cả danh sách ngành đăng ký: công ty mới đăng ký vài chục ngành, khớp mọi lĩnh vực.
    if not company.industry_guess:
        company.industry_guess = guess_industry_from_texts(
            [
                f"{company.company_name} {company.international_name}",
                company.industry,
                company.registered_industries.split(";")[0],
            ]
        )

    company.set_if_empty("legal_form", infer_legal_form(company.legal_name or company.company_name))

    for date_text in (company.license_date, company.operating_since, company.founded_year):
        year_match = re.search(r"(19|20)\d{2}", date_text or "")
        if year_match:
            company.set_if_empty("founded_year", year_match.group(0))
            company.set_if_empty("years_active", str(max(date.today().year - int(year_match.group(0)), 0)))

            return


def matches_keywords(
    company: Company,
    keywords: list[str],
) -> bool:
    """
    Công ty có chứa một trong các từ khóa không (không có từ khóa = nhận hết).
    """
    if not keywords:
        return True

    haystack = to_ascii_key(
        " ".join(
            [
                company.company_name,
                company.industry,
                company.registered_industries,
                company.industry_guess or guess_industry(f"{company.company_name} {company.industry}"),
            ]
        )
    )

    return any(to_ascii_key(keyword) in haystack for keyword in keywords)


def is_keyword_filtered(company: Company) -> bool:
    """
    Bộ lọc từ khóa chỉ áp dụng cho công ty tự tìm thấy, không lọc danh sách MKT tự đưa vào.
    """
    return company.discovered_by in (InfoDoanhNghiepSource.name, TraTenCongTySource.name)


def run_crawl(settings: Settings) -> int:
    """
    Chạy toàn bộ quy trình; trả về số công ty mới ghi được.
    """
    http_client = build_http_client(settings)
    info_doanh_nghiep_source = InfoDoanhNghiepSource(
        http_client,
        settings.infodoanhnghiep_delay_seconds,
        False,
    )
    tra_ten_cong_ty_source = TraTenCongTySource(
        http_client,
        settings.tratencongty_delay_seconds,
        settings.tratencongty_fetch_detail,
        settings.tratencongty_search_by_name,
        settings.cities,
    )
    enrichment_sources = build_enrichment_sources(
        settings,
        http_client,
        tra_ten_cong_ty_source,
    )
    logger.info(
        "Khu vực: %s | Nguồn đầu vào: %s | Nguồn bổ sung: %s | Từ khóa: %s",
        ", ".join(settings.cities),
        ", ".join((["file"] if settings.input_file else []) + settings.discovery_sources) or "không",
        ", ".join(source.name for source in enrichment_sources) or "không",
        ", ".join(settings.keywords) or "không lọc",
    )

    csv_store = CsvStore(settings.output_dir)
    written_count = 0
    try:
        companies = iter_discovered_companies(
            settings,
            info_doanh_nghiep_source,
            tra_ten_cong_ty_source,
        )
        for company in companies:
            if csv_store.is_known(company):
                continue

            contact_persons = enrich_company(
                company,
                enrichment_sources,
            )
            if csv_store.is_known(company):
                logger.info("  Bỏ qua (đã có, MST %s): %s", company.tax_code or "-", company.company_name)
                csv_store.remember(company)
                continue

            if is_keyword_filtered(company) and not matches_keywords(company, settings.keywords):
                logger.info("  Bỏ qua (không khớp từ khóa): %s", company.company_name)
                csv_store.remember(company)
                continue

            contact_persons = finalize_contacts(
                company,
                contact_persons,
            )
            csv_store.write(
                company,
                contact_persons,
            )
            written_count += 1
            logger.info(
                "  [%d] %s | %s | MST %s | SĐT %s | %d liên hệ | nguồn: %s",
                written_count,
                company.company_name,
                company.target_city,
                company.tax_code or "-",
                company.phone or "-",
                len(contact_persons),
                ", ".join(company.sources),
            )

            if settings.max_companies and written_count >= settings.max_companies:
                logger.info("Đã đạt giới hạn MAX_COMPANIES = %d", settings.max_companies)
                break
    finally:
        csv_store.close()

    return written_count
