from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo


SIGNAL_LABELS = {
    "STRONG_BUY": "强烈推荐",
    "BUY": "推荐",
    "WATCH": "观察",
    "PASS": "跳过",
    "BLOCK": "风控拦截",
}

RISK_LABELS = {
    "LOW": "低",
    "MEDIUM": "中",
    "HIGH": "高",
    "BLOCK": "拦截",
}

FIXTURE_STATUS_LABELS = {
    "scheduled": "未开赛",
    "live": "进行中",
    "finished": "已结束",
    "postponed": "已延期",
    "cancelled": "已取消",
    "unknown": "未知",
}

LEAGUE_LABELS = {
    "eng.1": "英格兰超级联赛",
    "esp.1": "西班牙甲级联赛",
    "ita.1": "意大利甲级联赛",
    "ger.1": "德国甲级联赛",
    "fra.1": "法国甲级联赛",
    "por.1": "葡萄牙超级联赛",
    "ned.1": "荷兰甲级联赛",
    "uefa.champions": "欧洲冠军联赛",
    "uefa.champions_qual": "欧洲冠军联赛资格赛",
    "uefa.europa": "欧足联欧洲联赛",
    "uefa.europa_qual": "欧足联欧洲联赛资格赛",
    "uefa.europa.conf": "欧足联欧洲协会联赛",
    "uefa.europa.conf_qual": "欧足联欧洲协会联赛资格赛",
    "uefa.super_cup": "欧洲超级杯",
    "uefa.nations": "欧洲国家联赛",
    "uefa.euro": "欧洲杯",
    "uefa.euroq": "欧洲杯预选赛",
    "fifa.world": "世界杯",
    "fifa.worldq.uefa": "世界杯欧洲区预选赛",
    "fifa.friendly": "国际友谊赛",
    "fifa.friendly_u21": "U21 国际友谊赛",
    "kor.1": "韩国 K1 联赛",
    "kor.2": "韩国 K2 联赛",
    "jpn.1": "日本 J1 联赛",
    "jpn.2": "日本 J2 联赛",
    "aus.1": "澳大利亚 A 联赛",
    "bra.1": "巴西甲级联赛",
    "bra.2": "巴西乙级联赛",
    "arg.1": "阿根廷甲级联赛",
    "arg.2": "阿根廷乙级联赛",
    "usa.1": "美国职业足球大联盟",
    "mex.1": "墨西哥甲级联赛",
    "mex.2": "墨西哥乙级联赛",
    "den.1": "丹麦超级联赛",
    "nor.1": "挪威超级联赛",
    "swe.1": "瑞典超级联赛",
    "club.friendly": "俱乐部友谊赛",
    "aff.championship": "东南亚足球锦标赛",
    "caf.w.nations": "女足非洲杯",
    "ecu.1": "厄瓜多尔甲级联赛",
    "chi.1": "智利甲级联赛",
    "bol.1": "玻利维亚甲级联赛",
    "tsdb:4457": "挪威甲级联赛",
}

LEAGUE_LABELS_BY_NAME = {
    "English Premier League": "英格兰超级联赛",
    "Spanish LaLiga": "西班牙甲级联赛",
    "Italian Serie A": "意大利甲级联赛",
    "German Bundesliga": "德国甲级联赛",
    "French Ligue 1": "法国甲级联赛",
    "Portuguese Primeira Liga": "葡萄牙超级联赛",
    "Dutch Eredivisie": "荷兰甲级联赛",
    "UEFA Champions League": "欧洲冠军联赛",
    "UEFA Europa League": "欧足联欧洲联赛",
    "UEFA Europa Conference League": "欧足联欧洲协会联赛",
    "FIFA World Cup": "世界杯",
    "International Friendly": "国际友谊赛",
    "Major League Soccer": "美国职业足球大联盟",
    "MLS": "美国职业足球大联盟",
    "Liga MX": "墨西哥甲级联赛",
    "Brazilian Serie A": "巴西甲级联赛",
    "Brazilian Serie B": "巴西乙级联赛",
    "Argentine Liga Profesional de Futbol": "阿根廷甲级联赛",
    "Argentine Primera Nacional": "阿根廷乙级联赛",
    "Australian A-League Men": "澳大利亚 A 联赛",
    "Japanese J.League": "日本 J1 联赛",
    "Danish Superliga": "丹麦超级联赛",
    "Norwegian Eliteserien": "挪威超级联赛",
    "Swedish Allsvenskan": "瑞典超级联赛",
    "Club Friendly": "俱乐部友谊赛",
    "ASEAN Championship": "东南亚足球锦标赛",
    "Women's Africa Cup of Nations": "女足非洲杯",
    "LigaPro Ecuador": "厄瓜多尔甲级联赛",
    "Chilean Primera Division": "智利甲级联赛",
    "Bolivian Liga Profesional": "玻利维亚甲级联赛",
    "Norwegian 1. Divisjon": "挪威甲级联赛",
}

TEAM_NAME_TRANSLATIONS = {
    "Atlético Goianiense": "戈亚尼亚竞技",
    "Atletico Goianiense": "戈亚尼亚竞技",
    "Atlético-GO": "戈亚尼亚竞技",
    "Operário PR": "欧帕瑞欧PR",
    "Operario PR": "欧帕瑞欧PR",
    "CRB": "雷加塔斯巴西",
    "Vila Nova": "维拉诺瓦",
    "Sport": "累西腓体育",
    "Sport Recife": "累西腓体育",
    "Cuiabá": "库亚巴",
    "Cuiaba": "库亚巴",
    "Atlanta": "亚特兰大竞技",
    "Almagro": "阿尔马格罗",
    "Randers FC": "兰讷斯",
    "Silkeborg IF": "锡尔克堡",
    "Rosenborg": "罗森博格",
    "Fredrikstad": "腓特烈斯塔",
    "BK Häcken": "赫根",
    "BK Hacken": "赫根",
    "AIK": "AIK索尔纳",
    "Galatasaray": "加拉塔萨雷",
    "Venezia": "威尼斯",
    "Singapore": "新加坡",
    "Timor-Leste": "东帝汶",
    "Indonesia": "印度尼西亚",
    "Cambodia": "柬埔寨",
    "South Africa": "南非",
    "Tanzania": "坦桑尼亚",
    "Ivory Coast": "科特迪瓦",
    "Burkina Faso": "布基纳法索",
    "Mushuc Runa": "穆苏克鲁纳",
    "Libertad (Ecuador)": "利伯塔德（厄瓜多尔）",
    "Guayaquil City FC": "瓜亚基尔城",
    "Universidad Católica (Quito)": "基多天主教大学",
    "Universidad Catolica (Quito)": "基多天主教大学",
    "Deportivo Cuenca": "昆卡体育",
    "Emelec": "埃梅莱克",
    "Unión La Calera": "拉卡莱拉联合",
    "Union La Calera": "拉卡莱拉联合",
    "Everton CD": "埃弗顿CD",
    "GV San José": "GV圣何塞",
    "GV San Jose": "GV圣何塞",
    "Universitario de Vinto": "温托大学生",
    "Stabæk": "斯塔贝克",
    "Stabaek": "斯塔贝克",
    "Hødd": "霍德",
    "Hodd": "霍德",
    "Palmeiras": "帕尔梅拉斯",
    "Flamengo": "弗拉门戈",
    "São Paulo": "圣保罗",
    "Sao Paulo": "圣保罗",
    "Corinthians": "科林蒂安",
    "Santos": "桑托斯",
    "Botafogo": "博塔弗戈",
    "Fluminense": "弗鲁米嫩塞",
    "Vasco da Gama": "瓦斯科达伽马",
    "Internacional": "巴西国际",
    "Grêmio": "格雷米奥",
    "Gremio": "格雷米奥",
    "Cruzeiro": "克鲁塞罗",
    "Bahia": "巴伊亚",
    "Fortaleza": "福塔莱萨",
    "Ceará": "塞阿拉",
    "Ceara": "塞阿拉",
    "Red Bull Bragantino": "布拉干蒂诺红牛",
    "Juventude": "尤文图德",
    "Vitória": "维多利亚",
    "Vitoria": "维多利亚",
    "Mirassol": "米拉索尔",
    "Athletico-PR": "巴拉纳竞技",
    "Athletico Paranaense": "巴拉纳竞技",
    "Coritiba": "科里蒂巴",
    "Goiás": "戈亚斯",
    "Goias": "戈亚斯",
    "Avaí": "阿瓦伊",
    "Avai": "阿瓦伊",
    "Chapecoense": "沙佩科恩斯",
    "Criciúma": "克里西乌马",
    "Criciuma": "克里西乌马",
    "Novorizontino": "诺沃里桑蒂诺",
    "América-MG": "米内罗美洲",
    "America-MG": "米内罗美洲",
    "Botafogo-SP": "博塔弗戈SP",
    "Ferroviária": "费罗维亚里亚",
    "Ferroviaria": "费罗维亚里亚",
    "Remo": "瑞模",
    "Paysandu": "帕桑度",
    "Amazonas": "亚马孙",
    "Volta Redonda": "沃尔塔雷东达",
    "Boca Juniors": "博卡青年",
    "River Plate": "河床",
    "Racing Club": "竞技俱乐部",
    "Independiente": "独立",
    "San Lorenzo": "圣洛伦索",
    "Estudiantes de La Plata": "拉普拉塔大学生",
    "Lanús": "拉努斯",
    "Lanus": "拉努斯",
    "Vélez Sarsfield": "萨斯菲尔德",
    "Velez Sarsfield": "萨斯菲尔德",
    "Newell's Old Boys": "纽维尔老男孩",
    "Rosario Central": "罗萨里奥中央",
    "Huracán": "飓风",
    "Huracan": "飓风",
    "Argentinos Juniors": "阿根廷青年人",
    "Defensa y Justicia": "国防与司法",
    "Talleres": "塔勒雷斯",
    "Belgrano": "贝尔格拉诺",
    "Godoy Cruz": "戈多伊克鲁斯",
    "Gimnasia La Plata": "拉普拉塔体操",
    "Banfield": "班菲尔德",
    "Tigre": "堤格雷",
    "Unión": "圣菲联合",
    "Union": "圣菲联合",
    "Sarmiento": "萨米恩托",
    "Platense": "普拉滕斯",
    "Instituto": "科尔多瓦学院",
    "Barracas Central": "巴拉卡斯中央",
    "Central Córdoba SdE": "圣地亚哥中央科尔多瓦",
    "Central Cordoba SdE": "圣地亚哥中央科尔多瓦",
    "Aldosivi": "阿尔多西维",
    "Deportivo Riestra": "里斯特雷体育",
    "Atlanta United FC": "亚特兰大联",
    "Inter Miami CF": "迈阿密国际",
    "LA Galaxy": "洛杉矶银河",
    "Los Angeles FC": "洛杉矶FC",
    "Seattle Sounders FC": "西雅图海湾人",
    "Portland Timbers": "波特兰伐木者",
    "New York City FC": "纽约城",
    "New York Red Bulls": "纽约红牛",
    "Philadelphia Union": "费城联合",
    "Orlando City SC": "奥兰多城",
    "Toronto FC": "多伦多FC",
    "CF Montréal": "蒙特利尔",
    "CF Montreal": "蒙特利尔",
    "FC Dallas": "达拉斯FC",
    "Houston Dynamo FC": "休斯敦迪纳摩",
    "Chicago Fire FC": "芝加哥火焰",
    "Real Salt Lake": "皇家盐湖城",
    "Club América": "墨西哥美洲",
    "America": "墨西哥美洲",
    "Cruz Azul": "蓝十字",
    "Guadalajara": "瓜达拉哈拉",
    "Chivas": "芝华士",
    "Tigres UANL": "老虎大学",
    "Monterrey": "蒙特雷",
    "Pumas UNAM": "美洲狮",
    "Toluca": "托卢卡",
    "Pachuca": "帕丘卡",
    "Santos Laguna": "桑托斯拉古纳",
    "León": "莱昂",
    "Leon": "莱昂",
    "Atlas": "阿特拉斯",
    "Kawasaki Frontale": "川崎前锋",
    "Yokohama F. Marinos": "横滨水手",
    "Urawa Red Diamonds": "浦和红钻",
    "Kashima Antlers": "鹿岛鹿角",
    "Vissel Kobe": "神户胜利船",
    "Sanfrecce Hiroshima": "广岛三箭",
    "FC Tokyo": "东京FC",
    "Gamba Osaka": "大阪钢巴",
    "Cerezo Osaka": "大阪樱花",
    "Nagoya Grampus": "名古屋鲸八",
    "Melbourne Victory": "墨尔本胜利",
    "Melbourne City FC": "墨尔本城",
    "Sydney FC": "悉尼FC",
    "Western Sydney Wanderers": "西悉尼流浪者",
    "Brisbane Roar": "布里斯班狮吼",
    "Adelaide United": "阿德莱德联",
    "Perth Glory": "珀斯光荣",
    "Central Coast Mariners": "中央海岸水手",
    "Newcastle Jets": "纽卡斯尔喷气机",
    "Manchester United": "曼联",
    "Manchester City": "曼城",
    "Liverpool": "利物浦",
    "Chelsea": "切尔西",
    "Arsenal": "阿森纳",
    "Tottenham Hotspur": "托特纳姆热刺",
    "Real Madrid": "皇家马德里",
    "Barcelona": "巴塞罗那",
    "Atletico Madrid": "马德里竞技",
    "Atlético Madrid": "马德里竞技",
    "Bayern Munich": "拜仁慕尼黑",
    "Borussia Dortmund": "多特蒙德",
    "Paris Saint-Germain": "巴黎圣日耳曼",
    "Juventus": "尤文图斯",
    "Inter Milan": "国际米兰",
    "AC Milan": "AC米兰",
    "Napoli": "那不勒斯",
    "Roma": "罗马",
}

def translate_signal(value: str) -> str:
    return SIGNAL_LABELS.get(str(value), str(value))


def translate_risk_level(value: str) -> str:
    return RISK_LABELS.get(str(value), str(value))


def translate_fixture_status(value: str) -> str:
    return FIXTURE_STATUS_LABELS.get(str(value), str(value))


def translate_league(league_id: str, fallback_name: str | None = None) -> str:
    return LEAGUE_LABELS.get(str(league_id), translate_league_name(fallback_name or str(league_id)))


def translate_league_name(name: str) -> str:
    return LEAGUE_LABELS_BY_NAME.get(str(name), str(name))


def translate_team_name(name: str | None) -> str:
    if not name:
        return "未知球队"
    cleaned = str(name).strip()
    return _TEAM_LOOKUP.get(_normalize_name(cleaned), cleaned)


def translate_match_text(match: str) -> str:
    text = str(match).replace(" 对阵 ", " vs ")
    parts = re.split(r"\s+vs\s+", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return f"{translate_team_name(parts[0])} 对阵 {translate_team_name(parts[1])}"
    return str(match)


def format_beijing_time(value: datetime | str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return str(value)
    return f"{parsed.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')} 北京时间"


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    collapsed = re.sub(r"\s+", " ", without_accents.replace(".", "").strip())
    return collapsed.casefold()




# Supplemental names that appear in free provider feeds and archived recommendations.
LEAGUE_LABELS.update({
    "usa.usl.1": "美国USL冠军联赛",
    "usa.usl.l1": "美国USL甲级联赛",
})

LEAGUE_LABELS_BY_NAME.update({
    "USL Championship": "美国USL冠军联赛",
    "USL League One": "美国USL甲级联赛",
    "American USL Championship": "美国USL冠军联赛",
    "American USL League One": "美国USL甲级联赛",
})

TEAM_NAME_TRANSLATIONS.update({
    "Greenville Triumph": "格林维尔凯旋",
    "Greenville Triumph SC": "格林维尔凯旋",
    "AC Boise": "博伊西竞技",
    "Athletic Club Boise": "博伊西竞技",
    "Pittsburgh Riverhounds": "匹兹堡猎犬河队",
    "Pittsburgh Riverhounds SC": "匹兹堡猎犬河队",
    "FC Tulsa": "塔尔萨FC",
    "Tulsa Roughnecks": "塔尔萨FC",
    "Louisville City": "路易斯维尔城",
    "Louisville City FC": "路易斯维尔城",
    "Birmingham Legion": "伯明翰军团",
    "Birmingham Legion FC": "伯明翰军团",
    "Charleston Battery": "查尔斯顿电池",
    "Tampa Bay Rowdies": "坦帕湾暴徒",
    "Indy Eleven": "印地十一",
    "North Carolina FC": "北卡罗来纳FC",
    "Phoenix Rising FC": "凤凰城崛起",
    "Sacramento Republic FC": "萨克拉门托共和",
    "San Antonio FC": "圣安东尼奥FC",
    "Orange County SC": "奥兰治县SC",
    "Detroit City FC": "底特律城",
    "Rhode Island FC": "罗德岛FC",
    "Hartford Athletic": "哈特福德竞技",
    "Loudoun United FC": "劳登联",
    "New Mexico United": "新墨西哥联",
    "Colorado Springs Switchbacks FC": "科罗拉多泉跃迁",
    "El Paso Locomotive FC": "埃尔帕索火车头",
    "Las Vegas Lights FC": "拉斯维加斯灯光",
    "Monterey Bay FC": "蒙特雷湾FC",
    "Oakland Roots SC": "奥克兰根源",
})



LEAGUE_LABELS.update({
    "usa.nwsl": "\u7f8e\u56fd\u5973\u8db3\u8054\u8d5b",
    "conmebol.sudamericana": "\u5357\u7f8e\u676f",
    "col.copa": "\u54e5\u4f26\u6bd4\u4e9a\u676f",
    "par.1": "\u5df4\u62c9\u572d\u7532\u7ea7\u8054\u8d5b",
    "slv.1": "\u8428\u5c14\u74e6\u591a\u7532\u7ea7\u8054\u8d5b",
})

LEAGUE_LABELS_BY_NAME.update({
    "UEFA Champions League Qualifying": "\u6b27\u6d32\u51a0\u519b\u8054\u8d5b\u8d44\u683c\u8d5b",
    "UEFA Europa Conference League Qualifying": "\u6b27\u8db3\u8054\u6b27\u6d32\u534f\u4f1a\u8054\u8d5b\u8d44\u683c\u8d5b",
    "CONMEBOL Sudamericana": "\u5357\u7f8e\u676f",
    "NWSL": "\u7f8e\u56fd\u5973\u8db3\u8054\u8d5b",
    "Copa Colombia": "\u54e5\u4f26\u6bd4\u4e9a\u676f",
    "Paraguayan Primera Division": "\u5df4\u62c9\u572d\u7532\u7ea7\u8054\u8d5b",
    "Salvadoran Primera Division": "\u8428\u5c14\u74e6\u591a\u7532\u7ea7\u8054\u8d5b",
})

TEAM_NAME_TRANSLATIONS.update({
    "Kairat Almaty": "\u963f\u62c9\u6728\u56fe\u51ef\u62c9\u7279",
    "Omonia Nicosia": "\u5c3c\u79d1\u897f\u4e9a\u5965\u83ab\u5c3c\u4e9a",
    "Omonia": "\u5965\u83ab\u5c3c\u4e9a",
    "CSU Craiova": "\u514b\u62c9\u7ea6\u74e6\u5927\u5b66",
    "Levski Sofia": "\u7d22\u83f2\u4e9a\u5217\u592b\u65af\u57fa",
    "Dukagjini": "\u675c\u5361\u5409\u5c3c",
    "FC Lugano": "\u5362\u52a0\u8bfa",
    "F.C. K\u00f8benhavn": "\u54e5\u672c\u54c8\u6839",
    "K\u00f8benhavn": "\u54e5\u672c\u54c8\u6839",
    "Polissya Zhitomir": "\u65e5\u6258\u7c73\u5c14\u6ce2\u5229\u897f\u4e9a",
    "Polissya": "\u6ce2\u5229\u897f\u4e9a",
    "Hapoel Be'er": "\u8d1d\u5c14\u8c22\u5df4\u590f\u666e\u5c14",
    "Hapoel Be'er Sheva": "\u8d1d\u5c14\u8c22\u5df4\u590f\u666e\u5c14",
    "Vikingur Reykjavik": "\u96f7\u514b\u96c5\u672a\u514b\u7ef4\u4eac\u53e4",
    "Vikingur": "\u7ef4\u4eac\u53e4",
    "Kauno Zalgiris": "\u8003\u8bfa\u624e\u5c14\u5409\u91cc\u65af",
    "KI Klaksvik": "\u514b\u62c9\u514b\u65af\u7ef4\u514b",
    "Lech Poznan": "\u6ce2\u5179\u5357\u83b1\u8d6b",
    "AGF": "\u5965\u80e1\u65af",
    "Gornik Zabrze": "\u624e\u5e03\u70ed\u77ff\u5de5",
    "Gornik Zabrz": "\u624e\u5e03\u70ed\u77ff\u5de5",
    "Fenerbahce": "\u8d39\u5185\u5df4\u5207",
    "Cerezo Osaka": "\u5927\u962a\u6a31\u82b1",
    "Borussia Dortmund": "\u591a\u7279\u8499\u5fb7",
    "Dortmund": "\u591a\u7279\u8499\u5fb7",
    "Liverpool": "\u5229\u7269\u6d66",
    "Wrexham": "\u96f7\u514b\u745f\u59c6",
    "Slovan Bratislava": "\u5e03\u62c9\u8fea\u65af\u62c9\u53d1\u65af\u6d1b\u4e07",
    "S Bratislava": "\u5e03\u62c9\u8fea\u65af\u62c9\u53d1\u65af\u6d1b\u4e07",
    "Iberia 1999": "\u4f0a\u6bd4\u5229\u4e9a1999",
    "Red Star Belgrade": "\u8d1d\u5c14\u683c\u83b1\u5fb7\u7ea2\u661f",
    "Red Star": "\u7ea2\u661f",
    "Larne": "\u62c9\u6069",
    "Rapid Vienna": "\u7ef4\u4e5f\u7eb3\u5feb\u901f",
    "Santa Coloma": "\u5723\u79d1\u6d1b\u9a6c",
    "Cienciano del Cusco": "\u5e93\u65af\u79d1\u897f\u6069\u590f\u8bfa",
    "Cienciano": "\u897f\u6069\u590f\u8bfa",
    "Sporting Cristal": "\u6c34\u6676\u4f53\u80b2",
    "MLS All-Stars": "MLS\u5168\u660e\u661f",
    "Liga MX All-Stars": "\u58a8\u897f\u54e5\u8054\u8d5b\u5168\u660e\u661f",
    "CD Municipal Lime\u00f1o": "\u5229\u6885\u5c3c\u5965\u5e02\u653f",
    "Municipal Lime\u00f1o": "\u5229\u6885\u5c3c\u5965\u5e02\u653f",
    "Inca Aruba": "\u5370\u52a0\u963f\u9c81\u5df4",
    "Nacional Asunci\u00f3n": "\u4e9a\u677e\u68ee\u56fd\u6c11",
    "Nacional": "\u56fd\u6c11\u961f",
    "Club Olimpia": "\u5965\u6797\u5339\u4e9a",
    "Olimpia": "\u5965\u6797\u5339\u4e9a",
    "Sportivo Luque\u00f1o": "\u5362\u514b\u5c3c\u5965\u4f53\u80b2",
    "Luque\u00f1o": "\u5362\u514b\u5c3c\u5965",
    "Sportivo Trinidense": "\u7279\u7acb\u5c3c\u767b\u65af\u4f53\u80b2",
    "Trinidense": "\u7279\u7acb\u5c3c\u767b\u65af",
    "Real Cartagena": "\u7687\u5bb6\u5361\u5854\u8d6b\u7eb3",
    "Cartagena": "\u5361\u5854\u8d6b\u7eb3",
    "Am\u00e9rica de Cali": "\u5361\u5229\u7f8e\u6d32",
    "Am\u00e9rica Cali": "\u5361\u5229\u7f8e\u6d32",
    "Atl\u00e9tico Junior": "\u5df4\u5170\u57fa\u4e9a\u9752\u5e74",
    "Atl. Junior": "\u5df4\u5170\u57fa\u4e9a\u9752\u5e74",
    "Barranquilla FC": "\u5df4\u5170\u57fa\u4e9aFC",
    "Barranquilla": "\u5df4\u5170\u57fa\u4e9a",
    "Inter Palmira": "\u5e15\u5c14\u7c73\u62c9\u56fd\u9645",
    "Internacional de Bogot\u00e1": "\u6ce2\u54e5\u5927\u56fd\u9645",
    "Forward Madison FC": "\u524d\u8fdb\u9ea6\u8fea\u900a",
    "Chattanooga Red Wolves": "\u67e5\u5854\u52aa\u52a0\u7ea2\u72fc",
    "Utah Royals": "\u72b9\u4ed6\u7687\u5bb6\u5973\u8db3",
    "Washington Spirit": "\u534e\u76db\u987f\u7cbe\u795e\u5973\u8db3",
    "Bay FC": "\u6d77\u6e7eFC",
    "Bay": "\u6d77\u6e7e",
    "Gotham FC": "\u54e5\u8c2dFC",
    "Gotham": "\u54e5\u8c2d",
    "Kansas City Current": "\u582a\u8428\u65af\u57ce\u6f6e\u6d41\u5973\u8db3",
    "Kansas City": "\u582a\u8428\u65af\u57ce",
    "Racing Louisville FC": "\u8def\u6613\u65af\u7ef4\u5c14\u7ade\u6280\u5973\u8db3",
    "Cameroon": "\u5580\u9ea6\u9686",
    "Mali": "\u9a6c\u91cc",
    "Ghana": "\u52a0\u7eb3",
    "Cape Verde": "\u4f5b\u5f97\u89d2",
    "Independiente Medell\u00edn": "\u9ea6\u5fb7\u6797\u72ec\u7acb",
    "Ind. Medell\u00edn": "\u9ea6\u5fb7\u6797\u72ec\u7acb",
    "Luis \u00c1ngel Firpo": "\u8def\u6613\u65af\u5b89\u8d6b\u5c14\u83f2\u5c14\u6ce2",
    "Fuerte San Francisco": "\u5bcc\u57c3\u5c14\u7279\u5723\u5f17\u6717\u897f\u65af\u79d1",
    "Fuerte SF": "\u5bcc\u57c3\u5c14\u7279\u5723\u5f17\u6717\u897f\u65af\u79d1",
    "Instituto (C\u00f3rdoba)": "\u79d1\u5c14\u591a\u74e6\u5b66\u9662",
    "Gimnasia LP": "\u62c9\u666e\u62c9\u5854\u4f53\u64cd",
    "Def. y Jus.": "\u56fd\u9632\u4e0e\u53f8\u6cd5",
})



# Dashboard/Telegram display overrides: keep visible names fully Chinese.
LEAGUE_LABELS.update({
    "usa.usl.championship": "\u7f8e\u56fd\u8db3\u7403\u51a0\u519b\u8054\u8d5b",
    "usa.usl.league_one": "\u7f8e\u56fd\u8db3\u7403\u7532\u7ea7\u8054\u8d5b",
})
LEAGUE_LABELS_BY_NAME.update({
    "USL Championship": "\u7f8e\u56fd\u8db3\u7403\u51a0\u519b\u8054\u8d5b",
    "American USL Championship": "\u7f8e\u56fd\u8db3\u7403\u51a0\u519b\u8054\u8d5b",
    "USL League One": "\u7f8e\u56fd\u8db3\u7403\u7532\u7ea7\u8054\u8d5b",
    "American USL League One": "\u7f8e\u56fd\u8db3\u7403\u7532\u7ea7\u8054\u8d5b",
})
TEAM_NAME_TRANSLATIONS.update({
    "Getafe": "\u8d6b\u5854\u8d39",
    "Atl\u00e9tico-MG": "\u7c73\u5185\u7f57\u7ade\u6280",
    "Atletico-MG": "\u7c73\u5185\u7f57\u7ade\u6280",
    "Atl\u00e9tico MG": "\u7c73\u5185\u7f57\u7ade\u6280",
    "Atletico MG": "\u7c73\u5185\u7f57\u7ade\u6280",
    "MLS All-Stars": "\u7f8e\u804c\u8054\u5168\u660e\u661f",
    "MLS All Stars": "\u7f8e\u804c\u8054\u5168\u660e\u661f",
    "Liga MX All-Stars": "\u58a8\u897f\u54e5\u8054\u8d5b\u5168\u660e\u661f",
    "Liga MX All Stars": "\u58a8\u897f\u54e5\u8054\u8d5b\u5168\u660e\u661f",
})

_TEAM_LOOKUP = {_normalize_name(key): value for key, value in TEAM_NAME_TRANSLATIONS.items()}
