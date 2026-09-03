from __future__ import annotations
import re

def collapse_doubled_layers(line: str) -> str:
    """
    Detect lines where >60% of characters appear doubled in sequence (AABBCC pattern)
    and collapse runs. A run of length k collapses to max(1, k // 2).
    Return the input unchanged when below threshold.
    """
    if not line or len(line) < 5:
        return line

    n = len(line)
    doubled_count = 0
    for i in range(n):
        is_doubled = False
        if i > 0 and line[i] == line[i-1]:
            is_doubled = True
        if i < n - 1 and line[i] == line[i+1]:
            is_doubled = True
        if is_doubled:
            doubled_count += 1

    ratio = doubled_count / n
    if ratio <= 0.60:
        return line

    # Collapse runs
    collapsed = []
    i = 0
    while i < n:
        char = line[i]
        run_len = 0
        while i + run_len < n and line[i + run_len] == char:
            run_len += 1
        
        collapsed_len = max(1, run_len // 2)
        collapsed.append(char * collapsed_len)
        i += run_len
        
    return "".join(collapsed)


def repair_hyphenation(text: str) -> str:
    """
    Join word-\\nrest and word- rest when wordrest (lowercased) appears elsewhere 
    in the document OR the fragment is not a standalone dictionary-ish token 
    (heuristic: next part starts lowercase). Keep real hyphenated compounds.
    """
    if not text:
        return text

    # Extract all lowercase standalone alphabetic words (length >= 2) to build a vocabulary
    words = re.findall(r'\b[a-zA-Z]{2,}\b', text)
    word_counts = {}
    for w in words:
        wl = w.lower()
        word_counts[wl] = word_counts.get(wl, 0) + 1
    
    # A word is considered valid if it appears at least 2 times (avoid split fragment noise)
    valid_words = {w for w, count in word_counts.items() if count >= 2}

    # Match word followed by a hyphen, then spacing/newlines, then another word
    pattern = r'\b([a-zA-Z]+)-\s*(\r?\n\s*|\s+)([a-zA-Z]+)\b'

    def replace_match(match):
        part1 = match.group(1)
        part2 = match.group(3)
        combined = part1 + part2
        combined_lower = combined.lower()

        is_part1_word = part1.lower() in valid_words
        is_part2_word = part2.lower() in valid_words

        # Join if combined word is elsewhere, or if one/both parts are not valid standalone words
        if combined_lower in valid_words or not is_part1_word or not is_part2_word:
            if part1.istitle():
                return combined.capitalize()
            elif part1.isupper():
                return combined.upper()
            else:
                return combined
        else:
            # Keep the hyphen but strip the trailing space/newline
            if part1.istitle():
                return part1.capitalize() + "-" + part2
            elif part1.isupper():
                return part1.upper() + "-" + part2
            else:
                return part1 + "-" + part2

    return re.sub(pattern, replace_match, text)


def repair_ligatures(text: str) -> str:
    """
    Fix fi/fl splits: suffi ciency -> sufficiency, fi rst -> first.
    Regex matches a word ending in f[il] followed by spaces/newlines and the next word,
    and joins if the joined word is in allowlist or occurs >= 2 times in the document.
    """
    if not text:
        return text

    # Count word occurrences
    words = re.findall(r'\b[a-zA-Z]+\b', text)
    word_counts = {}
    for w in words:
        wl = w.lower()
        word_counts[wl] = word_counts.get(wl, 0) + 1

    allowlist = {
        "first", "sufficient", "fellowship", "influence", "conflict", "afflict",
        "definition", "define", "final", "finally", "difficult", "difficulty",
        "flourish", "flat", "flight", "flow", "flower", "fluid", "fly", "flying",
        "official", "officer", "office", "efficiency", "efficient", "affliction",
        "conflict", "inflict", "conflate", "inflate", "deflate", "flu", "flush",
        "find", "finds", "finding", "findings", "terrific", "profit", "profitable",
        "flame", "fled", "flee", "fleet", "flesh", "float", "flock", "flood", "floor",
        "flowed", "flows", "flung", "flurry", "flute", "reflect", "reflection"
    }

    # Matches word ending with f[il], followed by one or more whitespace, followed by another word
    pattern = r'\b(\w*f[il])\s+(\w+)\b'

    def replace_match(match):
        part1 = match.group(1)
        part2 = match.group(2)
        combined = part1 + part2
        combined_lower = combined.lower()

        if combined_lower in allowlist or word_counts.get(combined_lower, 0) >= 2:
            if part1.istitle():
                return combined.capitalize()
            elif part1.isupper():
                return combined.upper()
            else:
                return combined
        else:
            return match.group(0)

    return re.sub(pattern, replace_match, text)


ABBREVIATIONS = {
    # Titles & honorifics
    "dr", "mr", "mrs", "ms", "messrs", "prof", "rev", "fr", "sr", "jr", "st",
    "gov", "sen", "rep", "gen", "col", "capt", "lt", "maj", "sgt", "hon", "pres",
    # Fellowships & orgs
    "aa", "na", "ca", "oiaa", "inc", "co", "corp", "ltd",
    # Latin / citations / reference
    "eg", "ie", "etc", "al", "vs", "v", "cf", "ca", "approx", "viz", "ibid", "op", "cit",
    "p", "pp", "vol", "vols", "no", "nos", "ch", "sec", "fig", "ed", "eds", "app", "monogr"
}


def is_abbreviation_ending(line: str) -> bool:
    """
    Detect if the trailing token of a line ends in an abbreviation or initial period
    rather than a true sentence termination (e.g. 'how long Dr.', 'with Bill W.', 'members of A.A.').
    """
    if not line:
        return False
    s = line.strip().rstrip("\x22\x27\u201d\u201c\u2019\u2018)]}")
    if not s.endswith("."):
        return False
    # Multi-dot acronyms: A.A., U.S., e.g., i.e., Ph.D.
    if re.search(r"\b(?:[A-Za-z]\.){2,}$", s):
        return True
    # Single uppercase initial: Bill W., Bob S., Emma K.
    if re.search(r"\b[A-Z]\.$", s):
        return True
    # Known abbreviation tokens: Dr., Mr., Mrs., St., etc.
    m = re.search(r"\b([a-zA-Z]+)\.$", s)
    if m and m.group(1).lower() in ABBREVIATIONS:
        return True
    # InDesign / bracket artifacts: [Dr., (Dr.
    if re.search(r"\[(?:Dr|Mr|Mrs|Ms|St|A\.A)\.$", s, re.IGNORECASE):
        return True
    return False


def is_terminal_sentence_ending(line: str) -> bool:
    """
    Check if a line ends in terminal punctuation (.?!:;) and is not an abbreviation.
    """
    if not line:
        return False
    s = line.strip().rstrip("\x22\x27\u201d\u201c\u2019\u2018)]}")
    if not s:
        return False
    if s[-1] in "?!":
        return True
    if s[-1] == ".":
        if s.endswith("..."):
            return True
        return not is_abbreviation_ending(line)
    if s[-1] in ":;":
        return True
    return False


def starts_list_or_heading(line: str) -> bool:
    """
    Heuristic helper to detect if a line starts a list item or heading.
    """
    s = line.strip()
    if not s:
        return False
    # Check bullet lists
    if re.match(r'^[\*\-\+•o]\s+', s):
        return True
    # Check numbered lists: 1., a., I., (1), (a), (I)
    if re.match(r'^(\d+|[a-zA-Z]|[iIvVxXldmCDM]+)[\.\)]\s+', s):
        return True
    if re.match(r'^\([\d+|[a-zA-Z]|[iIvVxXldmCDM]+\)\s+', s):
        return True
    # Check common heading tags/structures
    if re.match(r'^(Step|Chapter|Tradition|Concept|Part|Section)\b', s, re.IGNORECASE):
        return True
    # All caps and relatively short line
    words = s.split()
    if len(words) <= 10 and s.isupper():
        return True
    return False


def starts_heading_pattern(line: str) -> bool:
    """
    Heuristic helper to detect if a line is a standalone heading pattern.
    """
    s = line.strip()
    if not s:
        return False
    if re.match(r'^(Step|Chapter|Tradition|Concept|Part|Section)\b', s, re.IGNORECASE):
        return True
    # All caps and relatively short line
    words = s.split()
    if len(words) <= 10 and s.isupper():
        return True
    return False


def reflow_paragraphs(lines: list[str]) -> list[str]:
    """
    Join hard-wrapped lines into paragraphs: a line joins the previous one 
    unless the previous ends in terminal punctuation (.?!:;") and the next line is 
    not a lowercase continuation, or starts a list/heading pattern.
    Lines ending on abbreviations (e.g. 'Dr.', 'Mr.', 'Bill W.', 'A.A.') are never
    treated as terminal punctuation.
    """
    if not lines:
        return []

    reflowed = []
    current_line = ""

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            if current_line:
                reflowed.append(current_line)
                current_line = ""
            continue

        if not current_line:
            current_line = line_stripped
        else:
            prev_terminal = is_terminal_sentence_ending(current_line)
            prev_is_lh = starts_list_or_heading(current_line)
            starts_lh = starts_list_or_heading(line_stripped)
            next_is_lowercase = line_stripped[0].islower() if line_stripped else False

            if starts_lh or (prev_is_lh and not next_is_lowercase) or (prev_terminal and not next_is_lowercase):
                reflowed.append(current_line)
                current_line = line_stripped
            else:
                current_line = current_line + " " + line_stripped

    if current_line:
        reflowed.append(current_line)

    return reflowed

