from .cn_customs import CustomsSource
from .cn_mof import MOFSource
from .cn_nbs import NBSSource
from .cn_pboc import PBOCSource
from .cn_safe import SAFESource
from .us_rtdsm import RTDSMSource
from .oecd import OECDSource


CN_SOURCES = (NBSSource, PBOCSource, CustomsSource, MOFSource, SAFESource)
US_SOURCES = (RTDSMSource,)
GLOBAL_SOURCES = (OECDSource,)
ALL_SOURCES = CN_SOURCES + US_SOURCES + GLOBAL_SOURCES

__all__ = [
    "CN_SOURCES",
    "NBSSource",
    "PBOCSource",
    "CustomsSource",
    "MOFSource",
    "SAFESource",
    "RTDSMSource",
    "OECDSource",
    "ALL_SOURCES",
]
