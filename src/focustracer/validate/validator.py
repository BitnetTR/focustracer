"""
Trace Validator
===============
XML trace dosyalarını XSD şemalarıyla doğrular.
schema_version attribute'una göre v1/v2/v2.1/v2.2 XSD otomatik seçilir.
"""

from importlib import resources
from typing import Tuple, List


def _schema_dir():
    """`focustracer/schema/` içindeki XSD dosyalarına, kurulum yerinden
    bağımsız şekilde (editable install, wheel, `pip install git+...` vb.) erişir."""
    return resources.files("focustracer") / "schema"


def validate_xml_against_xsd(xml_path: str) -> Tuple[bool, List[str]]:
    """
    Trace XML dosyasını uygun XSD şemasıyla doğrula.

    Args:
        xml_path: XML dosyasının tam yolu

    Returns:
        (is_valid: bool, errors: list[str])
    """
    try:
        from lxml import etree  # type: ignore[attr-defined]
    except ImportError:
        return False, ["lxml kütüphanesi yüklü değil — `pip install lxml` ile kurun."]

    # 1) XML'i parse et
    try:
        tree = etree.parse(xml_path)
        root = tree.getroot()
    except etree.XMLSyntaxError as exc:
        return False, [f"XML sözdizimi hatası: {exc}"]

    # 2) schema_version attribute'ından dinamik XSD seçimi yap
    schema_ver = root.get("schema_version", "1.0")
    schema_dir = _schema_dir()

    # Tam schema versiyonunu kullan (örn: "2.1" ise trace_schema_v2.1.xsd)
    xsd_resource = schema_dir / f"trace_schema_v{schema_ver}.xsd"

    # Eğer tam sürüm yoksa (örn v2.1 yoksa), ana sürüme fallback yap ("v2")
    if not xsd_resource.is_file() and "." in schema_ver:
        major_ver = schema_ver.split(".")[0]
        xsd_resource = schema_dir / f"trace_schema_v{major_ver}.xsd"

    if not xsd_resource.is_file():
        return False, [f"XSD dosyası bulunamadı: `{xsd_resource}`"]

    # 3) XSD yükle ve doğrula
    try:
        with xsd_resource.open("rb") as f:
            xsd_doc = etree.parse(f)
        schema = etree.XMLSchema(xsd_doc)
    except Exception as exc:
        return False, [f"XSD yükleme hatası: {exc}"]

    is_valid = schema.validate(tree)
    errors   = [str(err) for err in schema.error_log]
    return is_valid, errors
