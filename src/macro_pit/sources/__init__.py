from .cn_customs import CustomsSource
from .cn_mof import MOFSource
from .cn_nbs import NBSSource
from .cn_pboc import PBOCMirrorSource, PBOCSource
from .cn_safe import SAFESource
from .us_rtdsm import RTDSMSource
from .oecd import OECDSource
from .cn_chinabond import ChinaBondSource
from .us_treasury import USTreasurySource
from .imf_commodity import IMFCommoditySource
from .cn_fallback import EastmoneyMacroSource, SinaMacroSource


CN_SOURCES = (NBSSource, PBOCSource, CustomsSource, MOFSource, SAFESource)
US_SOURCES = (RTDSMSource, USTreasurySource)
GLOBAL_SOURCES = (OECDSource,)
MARKET_SOURCES = (ChinaBondSource, IMFCommoditySource)
FALLBACK_SOURCES = (EastmoneyMacroSource, SinaMacroSource)
ALL_SOURCES = CN_SOURCES + US_SOURCES + GLOBAL_SOURCES + MARKET_SOURCES + FALLBACK_SOURCES

__all__ = [
    "CN_SOURCES",
    "NBSSource",
    "PBOCSource",
    "PBOCMirrorSource",
    "CustomsSource",
    "MOFSource",
    "SAFESource",
    "RTDSMSource",
    "OECDSource",
    "ChinaBondSource",
    "USTreasurySource",
    "IMFCommoditySource",
    "EastmoneyMacroSource",
    "SinaMacroSource",
    "FALLBACK_SOURCES",
    "MARKET_SOURCES",
    "ALL_SOURCES",
]
