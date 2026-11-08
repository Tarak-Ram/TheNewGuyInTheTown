"""Detecting "stop calling me" in the owner's speech, in three levels.

English only for now. Hindi and Telugu come with C-3 and must be added before any real owner is
called.

  1. CLEAR STOP  (is_stop_request)        "Stop calling me." "Don't call this number again."
     The call ends at once and the PG is opted out for every mover. Only unmistakable phrases
     are here, because a wrong opt-out is permanent for everyone.

  2. POSSIBLE STOP (needs_stop_confirmation)   "Please don't call me before eight." "I'm tired of
     these calls." "Not interested."
     A broad detector. The code makes the agent ask one question, "Would you like me to stop
     calling you?", and a clear yes opts the PG out. A false alarm costs one polite question,
     never a wrongful opt-out, so this detector may be as broad as it likes. That is what makes
     a "never miss a stop" rule achievable with patterns.

  3. END THE CALL (is_end_request)        "End this call." "I have to go."
     Ends only this call. Nothing else changes.

WHY THREE LEVELS. Phrase lists alone do not generalise. Tested on phrasings they had not been
tuned on, patterns for a single clear-stop level caught only 48% to 71% of real requests, every
time, however much they were tuned, and they also produced false stops. Asking when unsure
fixes the cause rather than the symptom.

The tests in tests/test_stop_requests_realistic.py are written from how people really speak.
When a real call shows a phrasing that was missed or wrongly caught, add it there first.
"""

import re

_CONTACT = r"(?:call|ring|phone|message|text)"
_PEST = r"(?:contact|bother|disturb|harass|pester)"
_NEG = r"(?:do\s*n'?t|do\s+not|never|please\s+do\s*n'?t)"
_ROBOT = r"(?:robots?|machines?|bots?|ai|recordings?|computers?|automated)"
# "again" and friends make a request permanent. "me" on its own may be followed by a time
# ("don't call me before eight"), so it only counts at the end of a sentence.
_STRONG = r"(?:again|anymore|any\s+more|ever)"
_WEAK = r"(?:me|us|this\s+number|here)"
_END_OF_SENTENCE = r"\s*(?:[.!?]|$)"

# -- level 1: clear stop -------------------------------------------------------------------------
_STOP_PATTERNS = [
    # "stop calling", "quit calling me", "enough, stop it", "stop this". Not "can't stop now".
    r"(?<!bus\s)(?<!auto\s)(?<!metro\s)(?<!can't\s)(?<!cannot\s)(?<!won't\s)(?<!didn't\s)"
    r"\b(?:stop|quit|enough)\b\W+(?:\w+\W+)?"
    r"(?:calling|ringing|phoning|bothering|disturbing|harassing|pestering|messaging|texting|"
    r"contacting|this|it|that)\b",
    # "stop these calls", "stop making these calls"
    r"\b(?:stop|quit)\s+(?:making\s+|doing\s+|sending\s+)?(?:these|those|such|all|the|this)\s+"
    r"(?:\w+\s+)?(?:calls?|messages?)\b",
    # a bare imperative: "Stop.", "Please stop", "I told you before, stop", "...? Stop"
    r"(?:^|[.!?,;]\s*)(?:please\s+|just\s+|now\s+|kindly\s+)?stop\b"
    r"(?!\s+(?:by|at|in|on|near|for|serving|the|here|there|over|to|and\s+(?:see|look)))",
    # "I want you to stop", "I request you not to call", "I told you to stop"
    r"\bwant\s+you\s+to\s+stop\b",
    r"\b(?:request|ask|asked|told|tell|beg)\s+you\s+(?:not\s+to|to\s+stop)\b",
    # "not to call me again", "can you please not call me again", "please not call me."
    rf"\bnot\s+(?:to\s+)?{_CONTACT}\s+(?:(?:me|us|this\s+number)\s+)?{_STRONG}\b",
    rf"\bnot\s+(?:to\s+)?{_CONTACT}\s+(?:me|us){_END_OF_SENTENCE}",
    # "no more calls", "no more AI calls", "Please, no more"
    r"\bno\s+more\s+(?:\w+\s+)?(?:calls?|ringing|phoning|messages?)\b",
    r"^\W*(?:please,?\s+)?no\s+more\W*$",
    # "don't call me again", "never ring this number again", "don't message or call me."
    rf"\b{_NEG}\s+(?:ever\s+)?{_CONTACT}(?:\s+(?:or|and)\s+{_CONTACT})?\s+"
    rf"(?:{_WEAK}\s+)?{_STRONG}\b",
    rf"\b{_NEG}\s+(?:ever\s+)?{_CONTACT}(?:\s+(?:or|and)\s+{_CONTACT})?\s+{_WEAK}"
    rf"{_END_OF_SENTENCE}",
    # a bare "do not call" that ends the sentence: "...for the last time, do not call."
    rf"\b{_NEG}\s+(?:ever\s+)?{_CONTACT}{_END_OF_SENTENCE}",
    # "do not bother us again", "don't disturb me."
    rf"\b{_NEG}\s+(?:ever\s+)?{_PEST}\s+(?:{_WEAK}\s+)?{_STRONG}\b",
    rf"\b{_NEG}\s+(?:ever\s+)?{_PEST}\s+(?:me|us){_END_OF_SENTENCE}",
    # "you keep disturbing me"
    r"\bkeep\s+(?:disturbing|bothering|calling|harassing|pestering|ringing|phoning)\b",
    # "I don't want these calls", "I don't wish to receive any calls", "...to be called"
    r"\b(?:do\s*n'?t|do\s+not)\s+(?:want|wish|need)\s+(?:any\s+|more\s+|these\s+|such\s+|"
    r"those\s+|this\s+kind\s+of\s+)*calls?\b",
    r"\b(?:do\s*n'?t|do\s+not)\s+(?:want|wish|need)\s+to\s+(?:receive|get)\s+(?:\w+\s+){0,3}?"
    r"calls?\b",
    r"\b(?:do\s*n'?t|do\s+not)\s+(?:want|wish|need)\s+to\s+be\s+(?:called|contacted|"
    r"disturbed|bothered)\b",
    # consent withdrawn: "I do not consent to these calls", "I withdraw my consent"
    r"\b(?:do\s*n'?t|do\s+not|never|no)\s+consent\b|\bwithdraw\w*\s+(?:my\s+|our\s+)?consent\b",
    # "I never agreed to these calls"
    r"\bnever\s+(?:agreed|consented|authori[sz]ed|permitted|allowed)\b.{0,25}\b(?:calls?|contact)",
    # "take me off your list", "remove my number", "delete my details", "remove it"
    r"\b(?:take|remove|delete|erase|wipe)\s+me\s+(?:off|from|out)\b",
    r"\b(?:take|remove|delete|erase|wipe)\b\W+(?:\w+\W+){0,2}?(?:my|our|this)\s+"
    r"(?:phone\s+)?(?:number|name|details|contact|data)\b",
    r"\bremove\s+it\b",
    # a bare "Remove me." / "Please erase it."
    r"^\W*(?:please\s+|kindly\s+)?(?:remove|delete|erase)\s+(?:me|it|this\s+number)\W*$",
    # "please refrain from phoning this number"
    r"\brefrain\s+from\s+(?:calling|phoning|ringing|contacting|messaging|disturbing)\b",
    # complaints: harassment, spam, blocking, reporting, police
    r"\bharass\w*\b",
    r"\b(?:this\s+is|it'?s|its)\s+spam\b",
    r"\bas\s+spam\b",
    r"\bblock\s+(?:this|your|the|that)\s+number\b",
    r"\b(?:going\s+to|i'?ll|will)\s+block\s+(?:you|this|it)\b",
    r"\bblocking\s+(?:you|your\s+number|this\s+number)\b",
    r"\b(?:file|lodge|make|register|raise)\s+(?:a\s+)?(?:complaint|police)\b",
    r"\breport\s+(?:you|this\s+number|this\s+call)\b",
    r"\b(?:call|contact|inform|involve)\s+(?:the\s+)?police\b",
    # objections to robots and AI
    r"\b(?:do\s*n'?t|do\s+not|not)\s+(?:want|like|comfortable)\b.{0,25}\b" + _ROBOT + r"\b",
    rf"\b(?:won'?t|will\s+not|refuse\s+to|can'?t|cannot|do\s*n'?t|do\s+not)\s+(?:talk|speak)\s+"
    rf"(?:to|with)\s+(?:a\s+|an\s+|the\s+)?(?:\w+\s+)?{_ROBOT}\b",
    r"\b(?:no|stop|hate|dislike|enough)\s+(?:\w+\s+){0,2}?(?:ai|robot|robotic|automated|bot|spam)"
    r"\s+calls?\b",
    # other clear signals
    r"\bleave\s+(?:me|us|him|her|them)\s+alone\b",
    r"\bhang\s+up\b",
    r"\bwrong\s+number\b",
    r"\bunsubscribe\b",
    r"\bopt\s*(?:me\s+)?out\b",
    r"\bdo\s+not\s+call\s+(?:list|registry)\b|\bdnd\b|\bndnc\b",
    r"\bi\s+(?:have|got)\s+no\s+interest\b",
]

# -- level 3: end only this call -------------------------------------------------------------------
_END_PATTERNS = [
    r"\b(?:end|cut|disconnect|finish|drop)\s+(?:this|the|that)\s+call\b",
    r"\bi\s+(?:have|need|must|got)\s+to\s+(?:go|leave)\b",
    # the owner saying goodbye is the owner ending the call
    r"\b(?:bye|goodbye)\b",
]

# -- level 2: possible stop. Broad on purpose: the worst outcome is one extra question. ---
# Phrases that contain a negative word but are not about the calls at all.
_NOT_A_SIGNAL = re.compile(
    r"\b(?:do\s*n'?t|do\s+not)\s+(?:worry|forget|hesitate|mind|be\s+shy)\b", re.IGNORECASE
)
_NEGATIVE = (
    r"(?:do\s*n'?t|do\s+not|never|no\s+more|cancel\w*|remove|delete|erase|withdraw\w*|report\w*)"
)
_ABOUT_CONTACT = (
    r"(?:calls?|calling|called|ring(?:ing)?|phon(?:e|ing)|messag\w*|text(?:ing)?|hear\s+from|"
    r"contact(?:ing)?\s+(?:me|us)|you\s+people|your\s+company|disturb\w*|bother\w*)"
)
_SIGNAL_ALONE = [
    r"\b(?:harass\w*|spam|irritat\w*|annoy\w*|fed\s+up|tired\s+of|sick\s+of|go\s+away|"
    r"opt\s*out|unsubscribe|withdraw\w*|complain\w*|police|not\s+interested)\b",
    r"\bleave\s+(?:me|us)\b",
    r"\b(?:block\w*|remove|delete|erase|report\w*)\b.{0,25}\b"
    r"(?:number|list|records|database|system|details|name)\b",
    r"\bno\s+(?:more\s+)?calls?\b",
    # annoyance and fatigue: "I'm done", "again and again", "that's the fifth call this week"
    r"\bi'?m\s+done\b|\bagain\s+and\s+again\b|\b(?:\w+th|second|third)\s+(?:call|time)\b",
    r"\bdisturb(?:ing)?\s+me\b|\bbother(?:ing)?\s+me\b|\bpester(?:ing)?\s+me\b",
    # threats: "my lawyer will hear about this", "if you call again I will..."
    r"\b(?:lawyer|advocate|court|legal\s+action|sue|cyber\s*cell|consumer\s+forum)\b",
    r"\bif\s+you\s+(?:call|ring|phone|contact)\b",
    # "marketing calls", "sales calls", "no interest"
    r"\b(?:marketing|sales|promotional|telemarket\w*|solicit\w*)\b",
    r"\bno\s+interest\b",
    # "please erase it", "remove me" said any way at all
    r"\b(?:erase|delete|remove)\s+(?:it|me|this)\b",
    r"\brefrain\b",
    # "we are not accepting any calls"
    r"\bnot\s+(?:accepting|taking|answering|receiving|entertaining)\b.{0,20}\bcalls?\b",
    # "I am not available for such calls", "I won't take any calls from you"
    r"\b(?:not\s+available|unavailable)\s+for\s+(?:such|these|those|any|your)\s+calls?\b",
    r"\b(?:won'?t|will\s+not|cannot|can'?t)\s+(?:take|accept|answer|receive)\s+"
    r"(?:any|such|these|your)\s+calls?\b",
    # a bare "stop" that is not "bus stop" or "stop by"
    r"(?<!bus\s)(?<!auto\s)(?<!metro\s)(?<!can't\s)(?<!cannot\s)(?<!won't\s)(?<!didn't\s)"
    r"\bstop\b(?!\s+(?:by|at|in|on|near|for|serving|the|here|there|over|to|and\s+(?:see|look)))",
    r"\bcall\s+(?:me\s+)?back\b.{0,15}\b(?:never|not)\b|\b(?:do\s*n'?t|do\s+not)\s+call\s+(?:me\s+)?back\b",
]

_STOP = [re.compile(p, re.IGNORECASE) for p in _STOP_PATTERNS]
_END = [re.compile(p, re.IGNORECASE) for p in _END_PATTERNS]
_ALONE = [re.compile(p, re.IGNORECASE) for p in _SIGNAL_ALONE]
_NEG_RE = re.compile(rf"\b{_NEGATIVE}\b", re.IGNORECASE)
_CONTACT_RE = re.compile(rf"\b{_ABOUT_CONTACT}\b", re.IGNORECASE)

# Answers to "Would you like me to stop calling you?"
_NO = re.compile(
    r"^\W*(?:no|nope|nah|not\s+really|never\s*mind|it'?s\s+(?:fine|ok|okay)|that'?s\s+"
    r"(?:fine|ok|okay)|continue|go\s+ahead|carry\s+on|keep\s+going|do\s*n'?t\s+stop|just\b)",
    re.IGNORECASE,
)
_YES = re.compile(
    r"^\W*(?:yes|yeah|yep|yup|please|correct|right|sure|exactly|definitely|absolutely|"
    r"that'?s\s+right|i\s+do|do\s+it|stop|haan|ji)\b",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    text = re.sub(r"[‘’`´]", "'", text)  # curly apostrophes from transcription
    text = re.sub(r"[-_]", " ", text)  # "do-not-call" is "do not call"
    return re.sub(r"\s+", " ", text.strip())


def is_stop_request(text: str) -> bool:
    """Level 1. A clear "leave me alone". Ends the call and opts the PG out for everyone."""
    cleaned = _normalise(text)
    return any(p.search(cleaned) for p in _STOP)


def is_end_request(text: str) -> bool:
    """Level 3. "End this call". Ends only this call. A clear stop always wins over this."""
    cleaned = _normalise(text)
    return not is_stop_request(cleaned) and any(p.search(cleaned) for p in _END)


def needs_stop_confirmation(text: str) -> bool:
    """Level 2. The owner may want the calls to stop. Ask them; do not decide for them."""
    cleaned = _normalise(text)
    if is_stop_request(cleaned) or is_end_request(cleaned):
        return False  # already handled
    cleaned = _NOT_A_SIGNAL.sub(" ", cleaned)
    if any(p.search(cleaned) for p in _ALONE):
        return True
    return bool(_NEG_RE.search(cleaned) and _CONTACT_RE.search(cleaned))


def answer_to_stop_question(text: str) -> str:
    """'yes', 'no' or 'unclear', for the owner's reply to "Would you like me to stop calling?"."""
    cleaned = _normalise(text)
    if _NO.search(cleaned):
        return "no"
    if _YES.search(cleaned):
        return "yes"
    return "unclear"
