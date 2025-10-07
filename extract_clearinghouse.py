#!/usr/bin/env python3
"""
Civil Rights Litigation Clearinghouse - 完整改进版数据提取器
生成与原Excel相同格式但数据更整洁的文件

改进点：
- 稳健的请求与重试、统一的超时设置
- 更健壮的字段解析与日期清洗（标准化为 YYYY-MM-DD，若无法解析保留原样）
- 改进法官/当事方/律师提取逻辑（优先结构化元素，其次文本回退）
- Excel 多工作表输出，与原思路一致但数据更整洁
- 脚本结束自动尝试打开生成的 Excel 文件（Linux/Mac/Windows 自适应），并提供 --no-open 选项
- 可通过命令行参数自定义 case_ids、输出路径、并行数（预留）、最大案件数、延迟
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ---------------------------- 配置常量 ----------------------------
DEFAULT_CASE_IDS = [17539, 16126, 17408, 17498, 11954, 10656, 12358, 16671, 16121, 14135]
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}
BASE_URL = "https://clearinghouse.net"
REQUEST_TIMEOUT_SECS = 30
MAX_RETRIES = 3
DELAY_BETWEEN_REQUESTS_SECS = 2


# ---------------------------- 工具函数 ----------------------------

def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_date_str(date_str: str) -> str:
    """将日期字符串尽力标准化为 YYYY-MM-DD；若失败则返回原字符串。"""
    if not date_str:
        return ""

    candidates = [
        "%B %d, %Y",   # January 2, 2024
        "%b %d, %Y",   # Jan 2, 2024
        "%b. %d, %Y",  # Jan. 2, 2024
        "%m/%d/%Y",    # 01/02/2024
        "%Y-%m-%d",    # 2024-01-02
    ]

    raw = clean_text(date_str)
    # 去除多余标点
    raw = raw.replace("\u00a0", " ").replace(" ,", ",").strip()

    for fmt in candidates:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            continue

    # 常见如 "January 2 2024"（无逗号）
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", raw)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y")
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    return raw  # 仍然返回原值，保证信息不丢失


def open_path_with_os(file_path: str) -> bool:
    """尝试用系统默认关联程序打开文件。返回是否成功。"""
    try:
        system_name = platform.system().lower()
        if system_name == "windows":
            os.startfile(file_path)  # type: ignore[attr-defined]
            return True
        if system_name == "darwin":  # macOS
            subprocess.run(["open", file_path], check=False)
            return True
        # Linux / other
        subprocess.run(["xdg-open", file_path], check=False)
        return True
    except Exception:
        return False


# ---------------------------- 数据结构 ----------------------------

@dataclass
class CaseData:
    case_id: str
    case_url: str
    scrape_timestamp: str
    case_name: str = ""
    court_name: str = ""
    docket_number: str = ""
    case_type: str = ""
    jurisdiction: str = ""
    status: str = ""
    filed_date: str = ""
    closed_date: str = ""
    judges: List[str] = field(default_factory=list)
    parties: List[str] = field(default_factory=list)
    plaintiffs: List[str] = field(default_factory=list)
    defendants: List[str] = field(default_factory=list)
    attorneys: List[str] = field(default_factory=list)
    description: str = ""
    case_summary: str = ""
    cause_of_action: List[str] = field(default_factory=list)
    nature_of_suit: str = ""
    claims: List[str] = field(default_factory=list)
    remedies_sought: List[str] = field(default_factory=list)
    outcome: str = "Unknown"
    overall_quality_score: float = 0.0


@dataclass
class DocketEntry:
    case_id: str
    entry_number: int
    date: str
    description: str
    document_type: str
    court_level: str


# ---------------------------- 抽取器 ----------------------------

class CaseExtractor:
    def __init__(self, case_id: int):
        self.case_id = case_id
        self.url = f"{BASE_URL}/case/{case_id}/"
        self.html: Optional[str] = None
        self.soup: Optional[BeautifulSoup] = None

    def fetch(self) -> bool:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print("    获取网页... ", end="")
                resp = requests.get(self.url, headers=HEADERS, timeout=REQUEST_TIMEOUT_SECS)
                resp.raise_for_status()
                self.html = resp.text
                # 优先 lxml，若无则 html.parser
                try:
                    self.soup = BeautifulSoup(self.html, "lxml")
                except Exception:
                    self.soup = BeautifulSoup(self.html, "html.parser")
                print("✓")
                return True
            except Exception as e:
                print(f"失败 (尝试 {attempt}/{MAX_RETRIES}) - {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(2)
        return False

    # ------------------------ 主信息抽取 ------------------------

    def extract_case_overview(self) -> CaseData:
        assert self.soup is not None
        data = CaseData(
            case_id=str(self.case_id),
            case_url=self.url,
            scrape_timestamp=datetime.now().isoformat(),
        )

        h1 = self.soup.find("h1")
        if h1:
            data.case_name = clean_text(h1.get_text())

        dl_data = self._extract_definition_lists()

        data.court_name = dl_data.get("court", "")
        data.docket_number = dl_data.get("docket_number", "")
        data.case_type = dl_data.get("case_type", "")
        data.jurisdiction = dl_data.get("jurisdiction", "")
        data.status = dl_data.get("status", "")

        data.filed_date = parse_date_str(dl_data.get("filing_date", ""))
        data.closed_date = parse_date_str(dl_data.get("closed_date", ""))

        data.judges = self._extract_judges(dl_data)

        parties_info = self._extract_parties(data.case_name)
        data.parties = parties_info.get("all_parties", [])
        data.plaintiffs = parties_info.get("plaintiffs", [])
        data.defendants = parties_info.get("defendants", [])

        data.attorneys = self._extract_attorneys()

        data.description = self._extract_description()
        data.case_summary = (data.description.split("\n\n")[0][:1000] if data.description else "")

        claims_info = self._extract_claims()
        data.cause_of_action = claims_info.get("causes", [])
        data.nature_of_suit = claims_info.get("nature", "")
        data.claims = claims_info.get("claims_list", [])
        data.remedies_sought = claims_info.get("remedies", [])

        data.outcome = self._extract_outcome()

        data.overall_quality_score = self._calculate_quality_score(data)
        return data

    def _extract_definition_lists(self) -> Dict[str, str]:
        assert self.soup is not None
        result: Dict[str, str] = {}

        key_map = {
            "filing date": "filing_date",
            "filed date": "filing_date",
            "closed date": "closed_date",
            "court": "court",
            "docket number": "docket_number",
            "case type": "case_type",
            "status": "status",
            "jurisdiction": "jurisdiction",
            "judge": "judge",
            "judges": "judges",
        }

        for dl in self.soup.find_all("dl"):
            dt_list = dl.find_all("dt")
            dd_list = dl.find_all("dd")
            for dt, dd in zip(dt_list, dd_list):
                k_raw = clean_text(dt.get_text()).lower().rstrip(":")
                v_raw = clean_text(dd.get_text())
                normalized = key_map.get(k_raw, k_raw.replace(" ", "_"))
                result[normalized] = v_raw
        return result

    def _extract_judges(self, dl_data: Dict[str, str]) -> List[str]:
        assert self.soup is not None
        judges: List[str] = []

        # 优先从定义列表中提取
        for judge_key in ("judge", "judges"):
            val = dl_data.get(judge_key)
            if val:
                parts = re.split(r";|,| and | & ", val)
                for p in parts:
                    name = clean_text(p)
                    if self._looks_like_person_name(name):
                        judges.append(name)

        # 回退：基于标题或文本正则搜索
        if not judges:
            text = self.soup.get_text(" ")
            patterns = [
                r"Judge\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)*\s+[A-Z][a-z]+)",
                r"Justice\s+([A-Z][a-z]+\s+[A-Z][a-z]+)",
                r"Hon\.\s+([A-Z][a-z]+\s+[A-Z]\.\s*[A-Z][a-z]+)",
                r"([A-Z][a-z]+),\s+(?:J\.|Chief Judge|District Judge)",
            ]
            for pat in patterns:
                for m in re.findall(pat, text):
                    name = clean_text(m)
                    if self._looks_like_person_name(name):
                        judges.append(name)

        # 去重
        uniq = sorted({j for j in judges if j})
        return uniq[:10]

    def _extract_parties(self, case_name: str) -> Dict[str, List[str]]:
        assert self.soup is not None
        result = {"all_parties": [], "plaintiffs": [], "defendants": []}

        # 1) 基于案件名称拆分 e.g., "Smith v. City of X" / "Smith vs. City of X"
        cn = clean_text(case_name)
        if cn:
            m = re.split(r"\s+v\.?s?\.?\s+", cn, flags=re.IGNORECASE)
            if len(m) == 2:
                left, right = m
                left_names = [clean_text(p) for p in re.split(r";|,| and | & ", left) if len(clean_text(p)) > 1]
                right_names = [clean_text(p) for p in re.split(r";|,| and | & ", right) if len(clean_text(p)) > 1]
                result["plaintiffs"].extend(left_names)
                result["defendants"].extend(right_names)

        # 2) 回退：在页面文本中启发式提取
        text = self.soup.get_text(" ")
        # Plaintiffs
        for pat in [
            r"Plaintiff[s]?:\s*([A-Za-z\s\.,&]+?)(?:Defendant|Attorney|Judge|\n\n|\r\n)",
            r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),?\s+(?:Plaintiff|v\.)",
        ]:
            for m in re.findall(pat, text, flags=re.IGNORECASE):
                name = clean_text(m)
                if 2 < len(name) < 100:
                    result["plaintiffs"].append(name)
        # Defendants
        for pat in [
            r"Defendant[s]?:\s*([A-Za-z\s\.,&]+?)(?:Attorney|Judge|Case|\n\n|\r\n)",
            r"v\.\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
        ]:
            for m in re.findall(pat, text, flags=re.IGNORECASE):
                name = clean_text(m)
                if 2 < len(name) < 100:
                    result["defendants"].append(name)

        all_parties = sorted({p for p in (result["plaintiffs"] + result["defendants"]) if p})
        result["all_parties"] = all_parties[:20]

        result["plaintiffs"] = sorted({p for p in result["plaintiffs"]})[:20]
        result["defendants"] = sorted({p for p in result["defendants"]})[:20]
        return result

    def _extract_attorneys(self) -> List[str]:
        assert self.soup is not None
        attys: List[str] = []
        # 链接与文本同时考虑
        for link in self.soup.find_all("a"):
            text = clean_text(link.get_text())
            if not text or len(text) > 100:
                continue
            low = text.lower()
            if any(k in low for k in ["attorney", "counsel", "esq", "llp", "law", "legal"]):
                attys.append(text)
        uniq = sorted({a for a in attys if len(a) > 3})
        return uniq[:20]

    def _extract_description(self) -> str:
        assert self.soup is not None
        paras: List[str] = []
        # 优先抓取长段落，过滤导航/提示
        for p in self.soup.find_all("p"):
            txt = clean_text(p.get_text())
            if len(txt) > 200 and not txt.lower().startswith("for pacer"):
                paras.append(txt)
        return "\n\n".join(paras[:3])

    def _extract_claims(self) -> Dict[str, List[str] | str]:
        assert self.soup is not None
        result: Dict[str, List[str] | str] = {
            "causes": [],
            "nature": "",
            "claims_list": [],
            "remedies": [],
        }
        text = self.soup.get_text(" ")

        cause_patterns = [
            r"42 U\.S\.C\. §?\s*\d+",
            r"Civil Rights Act",
            r"Constitutional [Cc]laim",
            r"First Amendment",
            r"Fourth Amendment",
            r"Eighth Amendment",
            r"Fourteenth Amendment",
        ]
        for pat in cause_patterns:
            if re.search(pat, text, flags=re.IGNORECASE):
                result["causes"].append(pat.replace("\\", ""))

        for kw in [
            "Civil Rights",
            "Constitutional",
            "Due Process",
            "Equal Protection",
            "Excessive Force",
            "Discrimination",
            "Free Speech",
        ]:
            if kw.lower() in text.lower():
                result["claims_list"].append(kw)

        for kw in [
            "Injunctive Relief",
            "Damages",
            "Declaratory Judgment",
            "Compensatory",
            "Punitive",
            "Attorney Fees",
        ]:
            if kw.lower() in text.lower():
                result["remedies"].append(kw)

        return result

    def _extract_outcome(self) -> str:
        assert self.soup is not None
        text = self.soup.get_text(" ").lower()
        checks = [
            ("Dismissed", ["dismissed", "dismissal"]),
            ("Settled", ["settled", "settlement", "consent decree"]),
            ("Granted", ["summary judgment granted", "motion granted", "granted in part"]),
            ("Denied", ["motion denied", "denied"]),
            ("Pending", ["pending", "ongoing"]),
        ]
        for label, kws in checks:
            if any(k in text for k in kws):
                return label
        return "Unknown"

    def _calculate_quality_score(self, d: CaseData) -> float:
        score = 0
        # 基本字段 (40)
        if d.case_name:
            score += 10
        if d.court_name:
            score += 10
        if d.docket_number:
            score += 10
        if d.filed_date:
            score += 10
        # 实体 (30)
        if d.judges:
            score += 10
        if d.plaintiffs:
            score += 10
        if d.defendants:
            score += 10
        # 内容 (30)
        if d.description and len(d.description) > 100:
            score += 10
        if d.cause_of_action:
            score += 10
        if d.outcome != "Unknown":
            score += 10
        return float(score)

    # ------------------------ 法庭记录抽取 ------------------------

    def extract_docket_entries(self) -> List[DocketEntry]:
        assert self.soup is not None
        rows: List[DocketEntry] = []
        entry_num = 1

        # 方法 1：表格
        for table in self.soup.find_all("table"):
            tr_list = table.find_all("tr")
            if len(tr_list) <= 1:
                continue
            for tr in tr_list[1:]:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                date_str = clean_text(cells[0].get_text())
                desc = clean_text(cells[1].get_text())
                rows.append(
                    DocketEntry(
                        case_id=str(self.case_id),
                        entry_number=entry_num,
                        date=parse_date_str(date_str),
                        description=desc,
                        document_type=self._classify_document_type(desc),
                        court_level=self._determine_court_level(desc),
                    )
                )
                entry_num += 1

        # 方法 2：列表项
        for li in self.soup.find_all("li"):
            text = clean_text(li.get_text())
            if len(text) < 20:
                continue
            m = re.search(r"(\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]+\s+\d{1,2},\s+\d{4})", text)
            date_val = parse_date_str(m.group(1)) if m else ""
            rows.append(
                DocketEntry(
                    case_id=str(self.case_id),
                    entry_number=entry_num,
                    date=date_val,
                    description=text,
                    document_type=self._classify_document_type(text),
                    court_level=self._determine_court_level(text),
                )
            )
            entry_num += 1

        return rows

    def _classify_document_type(self, text: str) -> str:
        low = text.lower()
        mapping = {
            "Complaint": ["complaint"],
            "Motion": ["motion"],
            "Order": ["order", "ordered"],
            "Opinion": ["opinion", "holding"],
            "Brief": ["brief"],
            "Judgment": ["judgment"],
            "Settlement": ["settlement", "consent decree"],
        }
        for key, kws in mapping.items():
            if any(k in low for k in kws):
                return key
        return "Other"

    def _determine_court_level(self, text: str) -> str:
        low = text.lower()
        if any(k in low for k in ["district court", "district judge"]):
            return "District Court"
        if any(k in low for k in ["circuit", "appellate", "appeals"]):
            return "Circuit Court"
        if any(k in low for k in ["supreme court", "scotus"]):
            return "Supreme Court"
        return "Unknown"

    def _looks_like_person_name(self, s: str) -> bool:
        if len(s) < 5 or " " not in s:
            return False
        bad = ["motion", "order", "filed", "granted", "denied", "settlement"]
        return not any(b in s.lower() for b in bad)


# ---------------------------- 统计报表 ----------------------------

def generate_data_quality_summary(all_cases: List[CaseData]) -> pd.DataFrame:
    total = len(all_cases)
    metrics = {
        "Total Cases": total,
        "Cases with Complete Basic Info": sum(1 for c in all_cases if c.case_name and c.docket_number),
        "Cases with Judges Info": sum(1 for c in all_cases if c.judges),
        "Cases with Parties Info": sum(1 for c in all_cases if c.plaintiffs or c.defendants),
        "Cases with Dates": sum(1 for c in all_cases if c.filed_date),
        "Cases with Outcome": sum(1 for c in all_cases if c.outcome and c.outcome != "Unknown"),
        "Average Quality Score": round(sum(c.overall_quality_score for c in all_cases) / total, 1) if total > 0 else 0,
    }
    return pd.DataFrame(list(metrics.items()), columns=["Metric", "Value"])


def generate_field_completeness(all_cases: List[CaseData]) -> pd.DataFrame:
    total = len(all_cases)
    fields_to_check = [
        "case_name", "court_name", "docket_number", "case_type", "jurisdiction",
        "status", "filed_date", "closed_date", "judges", "parties", "plaintiffs",
        "defendants", "attorneys", "description", "cause_of_action", "nature_of_suit",
        "case_summary", "claims", "remedies_sought", "outcome",
    ]

    rows = []
    for f in fields_to_check:
        non_empty = 0
        for c in all_cases:
            val = getattr(c, f)
            if isinstance(val, list):
                if len(val) > 0:
                    non_empty += 1
            elif isinstance(val, str):
                if val.strip():
                    non_empty += 1
            else:
                if val:
                    non_empty += 1
        pct = round((non_empty / total) * 100, 1) if total > 0 else 0
        rows.append({"Field": f, "Completeness (%)": pct, "Non-Empty Count": non_empty, "Total Cases": total})
    return pd.DataFrame(rows)


def generate_court_level_analysis(all_dockets: List[DocketEntry]) -> pd.DataFrame:
    if not all_dockets:
        return pd.DataFrame()
    df = pd.DataFrame([d.__dict__ for d in all_dockets])
    court_counts = df["court_level"].value_counts()
    total = len(df)
    rows = []
    for level, count in court_counts.items():
        rows.append({
            "Court Level": level,
            "Entry Count": int(count),
            "Percentage": round((count / total) * 100, 1) if total > 0 else 0,
        })
    return pd.DataFrame(rows)


def generate_document_type_analysis(all_dockets: List[DocketEntry]) -> pd.DataFrame:
    if not all_dockets:
        return pd.DataFrame()
    df = pd.DataFrame([d.__dict__ for d in all_dockets])
    doc_counts = df["document_type"].value_counts()
    total = len(df)
    rows = []
    for doc_type, count in doc_counts.items():
        rows.append({
            "Document Type": doc_type,
            "Count": int(count),
            "Percentage": round((count / total) * 100, 1) if total > 0 else 0,
        })
    return pd.DataFrame(rows)


# ---------------------------- 主流程 ----------------------------

def run(case_ids: List[int], delay_secs: int, no_open: bool, output_path: Optional[str], max_cases: Optional[int]) -> str:
    print("=" * 80)
    print("Civil Rights Litigation Clearinghouse")
    print("完整改进版数据提取器")
    print("=" * 80)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_file = output_path or f"legal_cases_clean_extraction_{timestamp}.xlsx"

    all_cases: List[CaseData] = []
    all_dockets: List[DocketEntry] = []

    # 限制数量
    target_ids = case_ids[: max_cases] if max_cases else case_ids

    for idx, cid in enumerate(target_ids, 1):
        print(f"\n[{idx}/{len(target_ids)}] 处理案件 {cid}")
        extractor = CaseExtractor(cid)
        if not extractor.fetch():
            print(f"  ✗ 无法获取案件 {cid}")
            continue

        print("    提取案件信息... ", end="")
        case_data = extractor.extract_case_overview()
        all_cases.append(case_data)
        print(f"✓ (质量分: {case_data.overall_quality_score:.1f})")

        print("    提取法庭记录... ", end="")
        docket_entries = extractor.extract_docket_entries()
        all_dockets.extend(docket_entries)
        print(f"✓ ({len(docket_entries)} 条)")

        if idx < len(target_ids):
            time.sleep(max(0, delay_secs))

    print("\n" + "=" * 80)
    print("生成Excel工作表...")
    print("=" * 80)

    print("  生成 Case Overview... ", end="")
    df_cases = pd.DataFrame([c.__dict__ for c in all_cases])
    # 列表字段转为 JSON 字符串，避免 Excel 展示为 Python 列表
    for col in df_cases.columns:
        if df_cases[col].dtype == "object":
            df_cases[col] = df_cases[col].apply(
                lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, list) else x
            )
    print("✓")

    print("  生成 All Docket Entries... ", end="")
    df_dockets = pd.DataFrame([d.__dict__ for d in all_dockets]) if all_dockets else pd.DataFrame()
    print("✓")

    print("  生成 Data Quality Summary... ", end="")
    df_quality = generate_data_quality_summary(all_cases)
    print("✓")

    print("  生成 Field Completeness... ", end="")
    df_completeness = generate_field_completeness(all_cases)
    print("✓")

    print("  生成 Court Level Analysis... ", end="")
    df_court_analysis = generate_court_level_analysis(all_dockets)
    print("✓")

    print("  生成 Document Type Analysis... ", end="")
    df_doc_analysis = generate_document_type_analysis(all_dockets)
    print("✓")

    print(f"\n保存到 {excel_file}... ", end="")
    with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
        df_cases.to_excel(writer, sheet_name="Case Overview", index=False)
        if not df_dockets.empty:
            df_dockets.to_excel(writer, sheet_name="All Docket Entries", index=False)
        df_quality.to_excel(writer, sheet_name="Data Quality Summary", index=False)
        df_completeness.to_excel(writer, sheet_name="Field Completeness", index=False)
        if not df_court_analysis.empty:
            df_court_analysis.to_excel(writer, sheet_name="Court Level Analysis", index=False)
        if not df_doc_analysis.empty:
            df_doc_analysis.to_excel(writer, sheet_name="Document Type Analysis", index=False)
    print("✓")

    print("\n" + "=" * 80)
    print("提取完成！")
    print("=" * 80)
    print(f"成功提取案件: {len(all_cases)}/{len(target_ids)}")
    print(f"法庭记录总数: {len(all_dockets)}")
    avg_q = (sum(c.overall_quality_score for c in all_cases) / len(all_cases)) if all_cases else 0.0
    print(f"平均质量分: {avg_q:.1f}")
    print(f"\n文件已保存: {excel_file}")
    print("\n工作表:")
    print("  1. Case Overview - 案件概览")
    print("  2. All Docket Entries - 法庭记录")
    print("  3. Data Quality Summary - 质量摘要")
    print("  4. Field Completeness - 字段完整性")
    print("  5. Court Level Analysis - 法院级别分析")
    print("  6. Document Type Analysis - 文档类型分析")

    if not no_open:
        print("\n正在尝试用系统默认程序打开文件...")
        opened = open_path_with_os(os.path.abspath(excel_file))
        if not opened:
            print("自动打开失败，请手动打开该路径中的文件：")
            print(os.path.abspath(excel_file))
    else:
        print("\n已根据参数禁用自动打开。")

    return excel_file


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Civil Rights Litigation Clearinghouse 数据提取器（改进版）")
    parser.add_argument(
        "--case-ids",
        type=str,
        default=",".join(str(cid) for cid in DEFAULT_CASE_IDS),
        help="逗号分隔的案件ID列表，默认内置示例",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=DELAY_BETWEEN_REQUESTS_SECS,
        help="相邻请求之间的延迟秒数（礼貌采集）",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="输出Excel文件路径（默认包含时间戳）",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="最多处理前N个案件（用于快速测试）",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="生成后不自动打开Excel文件",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    try:
        case_ids = [int(x.strip()) for x in args.case_ids.split(",") if x.strip()]
    except Exception:
        print("--case-ids 参数非法，应为逗号分隔的整数。", file=sys.stderr)
        sys.exit(2)

    run(case_ids=case_ids, delay_secs=args.delay, no_open=args.no_open, output_path=args.output, max_cases=args.max)


if __name__ == "__main__":
    main()
