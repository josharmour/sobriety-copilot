import re

# Ported from src/rag/retriever.py
_ENUMERATION_MARKER = re.compile(
    r"(?:Step|Tradition)\s+(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve)\s*(?:[:.)]|\d{1,3}\b)"
    r"|\b(?:[1-9]|1[0-2])\s*[.)]\s*(?:We\s+admitted|Came\s+to\s+believe|Made\s+a\s+(?:decision|list)"
    r"|Made\s+direct\s+amends|Were\s+entirely\s+ready|Humbly\s+asked|Continued\s+to\s+take"
    r"|Sought\s+through\s+prayer|Having\s+had\s+a\s+spiritual|Admitted\s+to\s+God|Became\s+willing)",
    re.IGNORECASE,
)
_CONTENTS_RE = re.compile(r"\bCONTENTS\b", re.IGNORECASE)

_PAGE_NUM_RE = re.compile(r"^(?:[Pp]age\s+\d+|\d+|[ivxlcdmIVXLCDM]+)$")


def is_title_like(s: str) -> bool:
    """
    Check if a string is Title Case or capitalization-heavy.
    """
    ignore_words = {"and", "the", "of", "to", "for", "in", "a", "an", "or", "with", "by", "at", "from"}
    words = re.findall(r'[a-zA-Z]+', s)
    if not words:
        return False
    
    capitalized_words = 0
    non_ignored_count = 0
    
    for w in words:
        if w.lower() in ignore_words:
            continue
        non_ignored_count += 1
        if w[0].isupper():
            capitalized_words += 1
            
    if non_ignored_count == 0:
        return s[0].isupper() if s else False
        
    return (capitalized_words / non_ignored_count) >= 0.75


def is_index(text: str) -> bool:
    """
    Detect if the text is part of an index page (e.g. term followed by page numbers).
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return False
    
    index_lines = 0
    for line in lines:
        # Matches "Abstinence, 4, 12, 18" or "Acceptance 12"
        if re.match(r'^[a-zA-Z\s\-]+,?\s*\d+(?:[\s,\-\d]*)$', line):
            index_lines += 1
            
    return (index_lines / len(lines)) >= 0.5


def starts_list_pattern(s: str) -> bool:
    """
    Helper to check if line starts with a list bullet or numbered list.
    """
    # Bullet points: *, -, •, o, +
    if re.match(r'^[\*\-\+•o]\s+', s):
        return True
    # Numbered lists: 1., a., I., (1), (a), (I)
    if re.match(r'^(\d+|[a-zA-Z]|[iIvVxXldmCDM]+)[\.\)]\s+', s):
        return True
    if re.match(r'^\([\d+|[a-zA-Z]|[iIvVxXldmCDM]+\)\s+', s):
        return True
    return False


def classify_block(
    text: str,
    position_on_page: float | None = None,
    running_headers: set[str] | None = None
) -> str:
    """
    Classify a text block into one of the canonical block types:
    heading | paragraph | list | toc | index | page_header | page_footer | footnote | epigraph | garbage
    """
    s = text.strip()
    if not s:
        return "garbage"

    # Check for Table of Contents dot leaders (e.g. "... 15") first
    # to avoid false-positive garbage classifications due to low alphanumeric ratio
    if re.search(r'\.{4,}', s):
        return "toc"

    # 1. Garbage detection (less than 40% alphanumeric chars)
    alnum_count = sum(1 for c in s if c.isalnum())
    if (alnum_count / len(s)) < 0.40:
        return "garbage"

    # 2. Page Header / Page Footer detection
    # Normalize text to match running headers
    normalized = re.sub(r"\d+", "#", s)
    is_running_header = running_headers and (normalized in running_headers)
    is_page_num = _PAGE_NUM_RE.match(s)

    if (is_running_header or is_page_num) and len(s.split()) <= 8:
        if position_on_page is not None:
            if position_on_page < 0.20:
                return "page_header"
            elif position_on_page > 0.80:
                return "page_footer"
        # Fallback if position is not known
        return "page_header"

    # 3. TOC detection
    if _CONTENTS_RE.search(s):
        return "toc"
    if len(_ENUMERATION_MARKER.findall(s)) >= 3:
        return "toc"

    # 4. Index detection
    if is_index(s):
        return "index"

    # 5. Footnote detection
    # Bottom of page and starts with footnote marker
    if position_on_page is not None and position_on_page > 0.75:
        if re.match(r'^\s*([\*\+†‡#¹²³⁴]|\d+)\s+', s):
            return "footnote"

    # 6. List detection
    if starts_list_pattern(s):
        return "list"

    # 7. Heading detection
    # Short line, no terminal sentence punctuation, title-case or all-caps
    words = s.split()
    if len(words) <= 12 and s[-1] not in '.?!:;"”':
        # Check if starts with Step/Chapter/etc.
        starts_heading_word = re.match(r'^(Step|Chapter|Tradition|Concept|Part|Section)\b', s, re.IGNORECASE)
        if starts_heading_word or s.isupper() or is_title_like(s):
            return "heading"

    # 8. Epigraph detection
    # Short quote enclosed in quotation marks
    if len(words) <= 45:
        quotes = ('"', "'", '“', '”', '‘', '’', '«', '»', '‹', '›')
        if s[0] in quotes and (s[-1] in quotes or (len(s) > 1 and s[-2] in quotes)):
            return "epigraph"

    # 9. Paragraph default
    return "paragraph"
