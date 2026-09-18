from bs4 import BeautifulSoup
import pytest
from macro_pit.sources.nbs_gdp import current_gdp
from macro_pit.errors import DataContractError

def page(quarter='3',header='比上年同期增长（%）',columns=True):
 return BeautifulSoup(f'<title>2015年{quarter}季度我国GDP初步核算结果</title><div class="txt-content"><table><tr><td></td><td>绝对额（亿元）</td><td>{header}</td></tr>'+('<tr><td>3季度</td><td>1-3季度</td><td>3季度</td><td>1-3季度</td></tr>' if columns else '')+'<tr><td>GDP</td><td>100</td><td>300</td><td>6.5</td><td>7.0</td></tr></table></div>','lxml')
def test_numeric_quarter_not_cumulative():assert current_gdp(page())==(2015,3,6.5)
@pytest.mark.parametrize('soup',[page(header='环比增长（%）'),page(columns=False),page(quarter='1-3')])
def test_reject_wrong_measure_or_cumulative(soup):
 with pytest.raises(DataContractError):current_gdp(soup)
