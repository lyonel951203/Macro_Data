from bs4 import BeautifulSoup
import pytest
from macro_pit.sources.nbs_gdp import current_gdp
from macro_pit.errors import DataContractError

def page(labels='2014年3季度4季度2015年1季度2季度',yoy='7.3 7.3 7.0 7.0',measure='GDP同比增长速度（%）'):
 return BeautifulSoup(f'<title>2015年1-2季度我国GDP初步核算情况</title><div class="txt-content"><table><tr><td></td><td>GDP环比增长速度（%）</td><td>{measure}</td></tr><tr><td>{labels}</td><td>1.9 1.5 1.4 1.7</td><td>{yoy}</td></tr></table></div>','lxml')
def test_merged_quarters_choose_current_yoy():assert current_gdp(page())==(2015,2,7.0)
@pytest.mark.parametrize('soup',[page(yoy='7.3 7.0 7.0'),page(labels='2014年3季度4季度2015年2季度1季度'),page(labels='3季度4季度1季度2季度'),page(measure='GDP累计同比增长速度（%）')])
def test_reject_unaligned_yearless_or_wrong_measure(soup):
 with pytest.raises(DataContractError):current_gdp(soup)
