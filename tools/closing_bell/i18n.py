"""Closing Bell — the anchor script's sentence templates in English, Hindi, Tamil, Marathi and Gujarati.

Owner decision (2026-10-28): every sentence is a fixed template translated once; each night only numbers,
company/sector names and dates are filled in. No machine translation at night. Numbers reach every language
through the same traced arguments (script_gen.Facts), so checks.py verifies them in all five.
Company, sector and strategy names stay in Latin script (code-mixed, as Indian business TV speaks them).

Template syntax: {arg} inserts an argument; {w:NAME:arg} looks up WORDS[lang][NAME][args[arg]] (direction words,
buy/sell, regime labels...). Optional clauses are separate keys.
NOTE: the Tamil, Marathi and Gujarati wording should get one native-speaker review; flag any change here.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List

LANGS = ["en", "hi", "ta", "mr", "gu"]
LABELS = {"en": "English", "hi": "हिंदी", "ta": "தமிழ்", "mr": "मराठी", "gu": "ગુજરાતી"}
VOICES = {"en": "en-US-AndrewMultilingualNeural", "hi": "hi-IN-MadhurNeural", "ta": "ta-IN-ValluvarNeural",
          "mr": "mr-IN-ManoharNeural", "gu": "gu-IN-NiranjanNeural"}
BASE_RATE = {"en": 8, "hi": 5, "ta": 8, "mr": 5, "gu": 5}          # percent, edge-tts
# phrases checks.py requires in every language (SEBI framing)
REQUIRED = {
    "en": ["not recommendations", "not investment advice"],
    "hi": ["सिफ़ारिशें नहीं", "निवेश सलाह नहीं"],
    "ta": ["பரிந்துரைகள் அல்ல", "முதலீட்டு ஆலோசனை அல்ல"],
    "mr": ["शिफारसी नाहीत", "गुंतवणूक सल्ला नाही"],
    "gu": ["ભલામણો નહીં", "રોકાણ સલાહ નથી"],
}

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "hi": ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
    "ta": ["ஜனவரி", "பிப்ரவரி", "மார்ச்", "ஏப்ரல்", "மே", "ஜூன்", "ஜூலை", "ஆகஸ்ட்", "செப்டம்பர்", "அக்டோபர்", "நவம்பர்", "டிசம்பர்"],
    "mr": ["जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून", "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"],
    "gu": ["જાન્યુઆરી", "ફેબ્રુઆરી", "માર્ચ", "એપ્રિલ", "મે", "જૂન", "જુલાઈ", "ઓગસ્ટ", "સપ્ટેમ્બર", "ઓક્ટોબર", "નવેમ્બર", "ડિસેમ્બર"],
}
WEEKDAYS = {  # Monday first
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "hi": ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"],
    "ta": ["திங்கட்கிழமை", "செவ்வாய்க்கிழமை", "புதன்கிழமை", "வியாழக்கிழமை", "வெள்ளிக்கிழமை", "சனிக்கிழமை", "ஞாயிற்றுக்கிழமை"],
    "mr": ["सोमवार", "मंगळवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"],
    "gu": ["સોમવાર", "મંગળવાર", "બુધવાર", "ગુરુવાર", "શુક્રવાર", "શનિવાર", "રવિવાર"],
}
AND = {"en": "and", "hi": "और", "ta": "மற்றும்", "mr": "आणि", "gu": "અને"}
STOP = {"en": ".", "hi": "।", "ta": ".", "mr": ".", "gu": "."}
RANGE = {"en": " to ", "hi": " से ", "ta": " முதல் ", "mr": " ते ", "gu": " થી "}

INDEX_NAMES = {   # index names read aloud; numbers stay digits (checks.py masks these name patterns)
    "Nifty 50": {"hi": "निफ्टी 50", "ta": "நிஃப்டி 50", "mr": "निफ्टी 50", "gu": "નિફ્ટી 50"},
    "Nifty 100": {"hi": "निफ्टी 100", "ta": "நிஃப்டி 100", "mr": "निफ्टी 100", "gu": "નિફ્ટી 100"},
    "Nifty 200": {"hi": "निफ्टी 200", "ta": "நிஃப்டி 200", "mr": "निफ्टी 200", "gu": "નિફ્ટી 200"},
    "Nifty 500": {"hi": "निफ्टी 500", "ta": "நிஃப்டி 500", "mr": "निफ्टी 500", "gu": "નિફ્ટી 500"},
    "Bank Nifty": {"hi": "बैंक निफ्टी", "ta": "பேங்க் நிஃப்டி", "mr": "बँक निफ्टी", "gu": "બેંક નિફ્ટી"},
    "the Next 50": {"hi": "निफ्टी नेक्स्ट 50", "ta": "நிஃப்டி நெக்ஸ்ட் 50", "mr": "निफ्टी नेक्स्ट 50", "gu": "નિફ્ટી નેક્સ્ટ 50"},
    "the Midcap 150": {"hi": "मिडकैप 150", "ta": "மிட்கேப் 150", "mr": "मिडकॅप 150", "gu": "મિડકેપ 150"},
    "the Smallcap 250": {"hi": "स्मॉलकैप 250", "ta": "ஸ்மால்கேப் 250", "mr": "स्मॉलकॅप 250", "gu": "સ્મોલકેપ 250"},
}
MACRO = {   # known macro releases by code; anything else keeps its English name
    "IN_IIP": {"hi": "औद्योगिक उत्पादन के आंकड़े", "ta": "தொழில்துறை உற்பத்தித் தரவு", "mr": "औद्योगिक उत्पादनाची आकडेवारी", "gu": "ઔદ્યોગિક ઉત્પાદનના આંકડા"},
    "IN_CPI": {"hi": "खुदरा महंगाई के आंकड़े", "ta": "சில்லறை பணவீக்கத் தரவு", "mr": "किरकोळ महागाईची आकडेवारी", "gu": "છૂટક મોંઘવારીના આંકડા"},
    "IN_WPI": {"hi": "थोक महंगाई के आंकड़े", "ta": "மொத்த விலை பணவீக்கத் தரவு", "mr": "घाऊक महागाईची आकडेवारी", "gu": "જથ્થાબંધ મોંઘવારીના આંકડા"},
    "IN_GDP": {"hi": "जीडीपी के आंकड़े", "ta": "ஜிடிபி தரவு", "mr": "जीडीपीची आकडेवारी", "gu": "જીડીપીના આંકડા"},
    "IN_RBI_POLICY": {"hi": "रिज़र्व बैंक की नीति", "ta": "ரிசர்வ் வங்கிக் கொள்கை", "mr": "रिझर्व्ह बँकेचे धोरण", "gu": "રિઝર્વ બેંકની નીતિ"},
    "US_FOMC": {"hi": "अमेरिकी फेड का ब्याज दर पर फ़ैसला", "ta": "அமெரிக்க பெடரல் ரிசர்வின் வட்டி விகித முடிவு", "mr": "अमेरिकी फेडचा व्याजदर निर्णय", "gu": "અમેરિકી ફેડનો વ્યાજદર નિર્ણય"},
    "US_CPI": {"hi": "अमेरिका के महंगाई आंकड़े", "ta": "அமெரிக்க பணவீக்கத் தரவு", "mr": "अमेरिकेची महागाई आकडेवारी", "gu": "અમેરિકાના મોંઘવારીના આંકડા"},
    "US_NFP": {"hi": "अमेरिका के रोज़गार आंकड़े", "ta": "அமெரிக்க வேலைவாய்ப்புத் தரவு", "mr": "अमेरिकेची रोजगार आकडेवारी", "gu": "અમેરિકાના રોજગારના આંકડા"},
    "US_GDP": {"hi": "अमेरिका के जीडीपी आंकड़े", "ta": "அமெரிக்க ஜிடிபி தரவு", "mr": "अमेरिकेची जीडीपी आकडेवारी", "gu": "અમેરિકાના જીડીપીના આંકડા"},
    "US_PCE": {"hi": "अमेरिका का PCE महंगाई सूचकांक", "ta": "அமெரிக்க PCE பணவீக்கக் குறியீடு", "mr": "अमेरिकेचा PCE महागाई निर्देशांक", "gu": "અમેરિકાનો PCE મોંઘવારી સૂચકાંક"},
    "US_JOBLESS_CLAIMS": {"hi": "अमेरिका के बेरोज़गारी दावे", "ta": "அமெரிக்க வேலையின்மை கோரிக்கைகள்", "mr": "अमेरिकेतील बेरोजगारी दावे", "gu": "અમેરિકાના બેરોજગારી દાવા"},
}
SECTION_TITLES = {   # transcript headings per segment tag: (tag, title)
    "HEADLINES": {"hi": ("मुख्य खबरें", "आज की सुर्खियाँ"), "ta": ("தலைப்புச் செய்திகள்", "இன்றைய முக்கியச் செய்திகள்"),
                  "mr": ("ठळक बातम्या", "आजचे मथळे"), "gu": ("મુખ્ય સમાચાર", "આજની હેડલાઇન્સ")},
    "MARKET WRAP": {"hi": ("बाज़ार का हाल", "बाज़ार कैसे बंद हुआ"), "ta": ("சந்தை நிலவரம்", "சந்தை எப்படி நிறைவடைந்தது"),
                    "mr": ("बाजाराचा आढावा", "बाजार कसा बंद झाला"), "gu": ("બજારનો હાલ", "બજાર કેવી રીતે બંધ થયું")},
    "RESULTS": {"hi": ("नतीजे", "नतीजे और बाज़ार का फ़ैसला"), "ta": ("முடிவுகள்", "முடிவுகளும் சந்தையின் தீர்ப்பும்"),
                "mr": ("निकाल", "निकाल आणि बाजाराचा कौल"), "gu": ("પરિણામ", "પરિણામ અને બજારનો ચુકાદો")},
    "SECTOR ROTATION": {"hi": ("सेक्टर रोटेशन", "पैसा किधर घूमा"), "ta": ("துறை சுழற்சி", "பணம் எங்கே நகர்ந்தது"),
                        "mr": ("सेक्टर रोटेशन", "पैसा कुठे फिरला"), "gu": ("સેક્ટર રોટેશન", "નાણાં ક્યાં ફર્યા")},
    "MOVERS & SHAKERS": {"hi": ("बड़े मूवर्स", "निफ्टी 50 · 100 · 200 · 500"), "ta": ("முக்கிய நகர்வுகள்", "நிஃப்டி 50 · 100 · 200 · 500"),
                         "mr": ("मोठ्या हालचाली", "निफ्टी 50 · 100 · 200 · 500"), "gu": ("મોટા મૂવર્સ", "નિફ્ટી 50 · 100 · 200 · 500")},
    "FII / DII": {"hi": ("FII / DII", "पैसे का प्रवाह"), "ta": ("FII / DII", "பண ஓட்டம்"),
                  "mr": ("FII / DII", "पैशाचा ओघ"), "gu": ("FII / DII", "નાણાંનો પ્રવાહ")},
    "TOP 10 IDEAS": {"hi": ("टॉप 10 आइडिया", "समीक्षा के लिए डेस्क के आइडिया"), "ta": ("டாப் 10 யோசனைகள்", "பரிசீலனைக்கான டெஸ்க் யோசனைகள்"),
                     "mr": ("टॉप 10 कल्पना", "आढाव्यासाठी डेस्कच्या कल्पना"), "gu": ("ટોપ 10 આઇડિયા", "સમીક્ષા માટે ડેસ્કના આઇડિયા")},
    "WHAT TO WATCH": {"hi": ("आगे क्या देखें", None), "ta": ("கவனிக்க வேண்டியவை", None),
                      "mr": ("पुढे काय पाहावे", None), "gu": ("આગળ શું જોવું", None)},
}

WORDS: Dict[str, Dict[str, Dict[str, str]]] = {
    "en": {
        "moved": {"up": "rose", "down": "fell", "flat": "was flat"},
        "dir": {"up": "up", "down": "down", "flat": "flat"},
        "nifty_verb": {"up": "closes higher", "down": "closes lower", "flat": "ends flat"},
        "buyers": {"buy": "buyers", "sell": "sellers"},
        "buying": {"buy": "buying", "sell": "selling"},
        "bought": {"buy": "bought", "sell": "sold"},
        "grew": {"up": "grew", "down": "fell"},
        "eased": {"up": "rose", "down": "eased", "flat": "was unchanged"},
        "jumped": {"big": "jumped", "small": "gained"},
        "sank": {"big": "sank", "small": "fell"},
        "lead_or_weak": {"lead": "leads the sectors, up", "weak": "is the weakest sector, down"},
        "regime": {"Mixed": "mixed", "Bear": "bearish", "Bull": "bullish", "Bearish": "bearish", "Bullish": "bullish", "Neutral": "neutral"},
        "trend": {"up": "up", "down": "down", "sideways": "sideways", "flat": "flat"},
    },
    "hi": {
        "moved": {"up": "चढ़ा", "down": "गिरा", "flat": "सपाट रहा"},
        "moved_pl": {"up": "चढ़े", "down": "गिरे", "flat": "सपाट रहे"},
        "conj": {"up": "चढ़कर", "down": "गिरकर", "flat": "लगभग सपाट रहकर"},
        "vixconj": {"up": "बढ़कर", "down": "घटकर", "flat": "स्थिर रहकर"},
        "net": {"buy": "खरीदारी", "sell": "बिकवाली"},
        "patmoved": {"up": "बढ़ा", "down": "घटा"},
        "chg": {"up": "बढ़त", "down": "गिरावट", "flat": "स्थिरता"},
        "regime": {"Mixed": "मिला-जुला", "Bear": "मंदी का", "Bull": "तेज़ी का", "Bearish": "मंदी का", "Bullish": "तेज़ी का", "Neutral": "तटस्थ"},
        "trend": {"up": "ऊपर की ओर", "down": "नीचे की ओर", "sideways": "सपाट", "flat": "सपाट"},
    },
    "ta": {
        "moved": {"up": "உயர்ந்தது", "down": "சரிந்தது", "flat": "மாற்றமின்றி இருந்தது"},
        "moved_pl": {"up": "உயர்ந்தன", "down": "சரிந்தன", "flat": "மாற்றமின்றி இருந்தன"},
        "conj": {"up": "உயர்ந்து", "down": "சரிந்து", "flat": "மாற்றமின்றி"},
        "vixconj": {"up": "உயர்ந்து", "down": "குறைந்து", "flat": "மாற்றமின்றி"},
        "net": {"buy": "கொள்முதல்", "sell": "விற்பனை"},
        "patmoved": {"up": "அதிகரித்தது", "down": "குறைந்தது"},
        "chg": {"up": "உயர்வு", "down": "சரிவு", "flat": "மாற்றமின்மை"},
        "regime": {"Mixed": "கலவையான", "Bear": "சரிவு", "Bull": "ஏற்ற", "Bearish": "சரிவு", "Bullish": "ஏற்ற", "Neutral": "நடுநிலை"},
        "trend": {"up": "ஏறுமுகம்", "down": "இறங்குமுகம்", "sideways": "சமநிலை", "flat": "சமநிலை"},
    },
    "mr": {
        "moved": {"up": "वाढला", "down": "घसरला", "flat": "स्थिर राहिला"},
        "moved_pl": {"up": "वाढले", "down": "घसरले", "flat": "स्थिर राहिले"},
        "conj": {"up": "वाढून", "down": "घसरून", "flat": "स्थिर राहून"},
        "vixconj": {"up": "वाढून", "down": "घटून", "flat": "स्थिर राहून"},
        "net": {"buy": "खरेदी", "sell": "विक्री"},
        "net_of": {"buy": "खरेदीचा", "sell": "विक्रीचा"},
        "patmoved": {"up": "वाढला", "down": "घटला"},
        "chg": {"up": "वाढ", "down": "घसरण", "flat": "स्थिरता"},
        "regime": {"Mixed": "संमिश्र", "Bear": "मंदीची", "Bull": "तेजीची", "Bearish": "मंदीची", "Bullish": "तेजीची", "Neutral": "तटस्थ"},
        "trend": {"up": "वरच्या दिशेने", "down": "खालच्या दिशेने", "sideways": "सपाट", "flat": "सपाट"},
    },
    "gu": {
        "moved": {"up": "વધ્યો", "down": "ઘટ્યો", "flat": "સ્થિર રહ્યો"},
        "moved_pl": {"up": "વધ્યા", "down": "ઘટ્યા", "flat": "સ્થિર રહ્યા"},
        "conj": {"up": "વધીને", "down": "ઘટીને", "flat": "સ્થિર રહીને"},
        "vixconj": {"up": "વધીને", "down": "ઘટીને", "flat": "સ્થિર રહીને"},
        "net": {"buy": "ખરીદી", "sell": "વેચવાલી"},
        "net_of": {"buy": "ખરીદીનો", "sell": "વેચવાલીનો"},
        "patmoved": {"up": "વધ્યો", "down": "ઘટ્યો"},
        "chg": {"up": "વધારો", "down": "ઘટાડો", "flat": "સ્થિરતા"},
        "regime": {"Mixed": "મિશ્ર", "Bear": "મંદીનું", "Bull": "તેજીનું", "Bearish": "મંદીનું", "Bullish": "તેજીનું", "Neutral": "તટસ્થ"},
        "trend": {"up": "ઉપર તરફ", "down": "નીચે તરફ", "sideways": "સપાટ", "flat": "સપાટ"},
    },
}

# ------------------------------------------------------------------------------------------------ templates
T: Dict[str, Dict[str, str]] = {
    # ---- s0 headlines
    "welcome.0": {"en": "Good evening, and welcome to Closing Bell on the Nivesh Desk."},
    "welcome.1": {"en": "Good evening. This is Closing Bell, from the Nivesh Desk."},
    "welcome.2": {"en": "Good evening, and welcome to Closing Bell on the Nivesh Desk, your wrap of the day's markets."},
    "welcome": {"hi": "नमस्कार, निवेश डेस्क से क्लोज़िंग बेल में आपका स्वागत है।",
                "ta": "வணக்கம், நிவேஷ் டெஸ்கின் க்ளோசிங் பெல் நிகழ்ச்சிக்கு உங்களை வரவேற்கிறோம்.",
                "mr": "नमस्कार, निवेश डेस्कवरील क्लोजिंग बेलमध्ये आपले स्वागत आहे.",
                "gu": "નમસ્કાર, નિવેશ ડેસ્ક પરથી ક્લોઝિંગ બેલમાં આપનું સ્વાગત છે."},
    "heads_intro": {"en": "Here are tonight's headlines.", "hi": "आज की मुख्य खबरें।", "ta": "இன்றைய முக்கியச் செய்திகள்.",
                    "mr": "आजच्या ठळक बातम्या.", "gu": "આજના મુખ્ય સમાચાર."},
    "h1_flat_sc.up": {"en": "The Nifty ends flat, but smallcaps jump {p} percent.",
                      "hi": "निफ्टी सपाट बंद हुआ, लेकिन स्मॉलकैप शेयर {p} प्रतिशत उछले।",
                      "ta": "நிஃப்டி மாற்றமின்றி நிறைவடைந்தது, ஆனால் ஸ்மால்கேப் பங்குகள் {p} சதவீதம் உயர்ந்தன.",
                      "mr": "निफ्टी सपाट बंद झाला, पण स्मॉलकॅप शेअर्स {p} टक्क्यांनी वाढले.",
                      "gu": "નિફ્ટી સપાટ બંધ થયો, પરંતુ સ્મોલકેપ શેરો {p} ટકા વધ્યા."},
    "h1_flat_sc.down": {"en": "The Nifty ends flat, but smallcaps fall {p} percent.",
                        "hi": "निफ्टी सपाट बंद हुआ, लेकिन स्मॉलकैप शेयर {p} प्रतिशत टूटे।",
                        "ta": "நிஃப்டி மாற்றமின்றி நிறைவடைந்தது, ஆனால் ஸ்மால்கேப் பங்குகள் {p} சதவீதம் சரிந்தன.",
                        "mr": "निफ्टी सपाट बंद झाला, पण स्मॉलकॅप शेअर्स {p} टक्क्यांनी घसरले.",
                        "gu": "નિફ્ટી સપાટ બંધ થયો, પરંતુ સ્મોલકેપ શેરો {p} ટકા ઘટ્યા."},
    "h1_move": {"en": "The Nifty {w:nifty_verb:d}, {w:dir:d} {p} percent at {close}.",
                "hi": "निफ्टी {p} प्रतिशत {w:conj:d} {close} पर बंद हुआ।",
                "ta": "நிஃப்டி {p} சதவீதம் {w:conj:d} {close} புள்ளிகளில் நிறைவடைந்தது.",
                "mr": "निफ्टी {p} टक्क्यांनी {w:conj:d} {close} वर बंद झाला.",
                "gu": "નિફ્ટી {p} ટકા {w:conj:d} {close} પર બંધ થયો."},
    "h1_flat": {"en": "The Nifty ends nearly flat at {close}.", "hi": "निफ्टी {close} पर लगभग सपाट बंद हुआ।",
                "ta": "நிஃப்டி {close} புள்ளிகளில் ஏறக்குறைய மாற்றமின்றி நிறைவடைந்தது.", "mr": "निफ्टी {close} वर जवळपास सपाट बंद झाला.",
                "gu": "નિફ્ટી {close} પર લગભગ સપાટ બંધ થયો."},
    "broad": {"en": "{items}.", "hi": "{items}।", "ta": "{items}.", "mr": "{items}.", "gu": "{items}."},
    "sp": {"en": " ", "hi": " ", "ta": " ", "mr": " ", "gu": " "},
    "stop": {"en": ".", "hi": "।", "ta": ".", "mr": ".", "gu": "."},
    "h2": {"en": "Foreign investors were net {w:buyers:b} of {amt} crore rupees.",
           "hi": "विदेशी निवेशकों ने {amt} करोड़ रुपये की शुद्ध {w:net:b} की।",
           "ta": "வெளிநாட்டு முதலீட்டாளர்கள் {amt} கோடி ரூபாய்க்கு நிகர {w:net:b} செய்தனர்.",
           "mr": "परदेशी गुंतवणूकदारांनी {amt} कोटी रुपयांची निव्वळ {w:net:b} केली.",
           "gu": "વિદેશી રોકાણકારોએ {amt} કરોડ રૂપિયાની ચોખ્ખી {w:net:b} કરી."},
    "h2_since": {"en": "Foreign investors were net {w:buyers:b} of {amt} crore rupees, their biggest {w:buying:b} day since {since}.",
                 "hi": "विदेशी निवेशकों ने {amt} करोड़ रुपये की शुद्ध {w:net:b} की, जो {since} के बाद {w:net:b} का सबसे बड़ा दिन है।",
                 "ta": "வெளிநாட்டு முதலீட்டாளர்கள் {amt} கோடி ரூபாய்க்கு நிகர {w:net:b} செய்தனர்; இது {since} க்குப் பிறகு மிகப்பெரிய {w:net:b} நாள்.",
                 "mr": "परदेशी गुंतवणूकदारांनी {amt} कोटी रुपयांची निव्वळ {w:net:b} केली; {since} नंतरचा हा {w:net_of:b} सर्वात मोठा दिवस.",
                 "gu": "વિદેશી રોકાણકારોએ {amt} કરોડ રૂપિયાની ચોખ્ખી {w:net:b} કરી, જે {since} પછીનો {w:net_of:b} સૌથી મોટો દિવસ છે."},
    "h3": {"en": "Results-day rallies in {names}.", "hi": "नतीजों के दिन {names} में तेज़ी रही।",
           "ta": "முடிவுகள் வெளியான நாளில் {names} பங்குகள் உயர்ந்தன.", "mr": "निकालांच्या दिवशी {names} यांच्या शेअर्समध्ये तेजी आली.",
           "gu": "પરિણામના દિવસે {names}માં તેજી આવી."},
    "h4.lead": {"en": "And {sector} leads the sectors, up {p} percent. All of it, straight from the Smart Trading Desk.",
                "hi": "और {sector} सेक्टर {p} प्रतिशत चढ़कर सबसे आगे रहा। ये सब, सीधे स्मार्ट ट्रेडिंग डेस्क से।",
                "ta": "{sector} துறை {p} சதவீதம் உயர்ந்து முன்னிலை வகித்தது. இவை அனைத்தும், நேரடியாக ஸ்மார்ட் டிரேடிங் டெஸ்கிலிருந்து.",
                "mr": "आणि {sector} क्षेत्र {p} टक्क्यांनी वाढून आघाडीवर राहिले. हे सर्व, थेट स्मार्ट ट्रेडिंग डेस्कवरून.",
                "gu": "અને {sector} સેક્ટર {p} ટકા વધીને સૌથી આગળ રહ્યું. આ બધું, સીધું સ્માર્ટ ટ્રેડિંગ ડેસ્ક પરથી."},
    "h4.weak": {"en": "And {sector} is the weakest sector, down {p} percent. All of it, straight from the Smart Trading Desk.",
                "hi": "और {sector} सेक्टर {p} प्रतिशत गिरकर सबसे कमज़ोर रहा। ये सब, सीधे स्मार्ट ट्रेडिंग डेस्क से।",
                "ta": "{sector} துறை {p} சதவீதம் சரிந்து மிகவும் பலவீனமாக இருந்தது. இவை அனைத்தும், நேரடியாக ஸ்மார்ட் டிரேடிங் டெஸ்கிலிருந்து.",
                "mr": "आणि {sector} क्षेत्र {p} टक्क्यांनी घसरून सर्वात कमकुवत ठरले. हे सर्व, थेट स्मार्ट ट्रेडिंग डेस्कवरून.",
                "gu": "અને {sector} સેક્ટર {p} ટકા ઘટીને સૌથી નબળું રહ્યું. આ બધું, સીધું સ્માર્ટ ટ્રેડિંગ ડેસ્ક પરથી."},
    # ---- s1 market wrap
    "score": {"en": "First, the scoreboard. The Nifty 50 settled at {close}, {w:dir:d} {pts} points, or {pct} percent.",
              "hi": "सबसे पहले बाज़ार का हाल। निफ्टी 50 {pts} अंक यानी {pct} प्रतिशत {w:conj:d} {close} पर बंद हुआ।",
              "ta": "முதலில் சந்தை நிலவரம். நிஃப்டி 50 {pts} புள்ளிகள், அதாவது {pct} சதவீதம் {w:conj:d} {close} புள்ளிகளில் நிறைவடைந்தது.",
              "mr": "सुरुवातीला बाजाराचा आढावा. निफ्टी 50 {pts} अंकांनी म्हणजे {pct} टक्क्यांनी {w:conj:d} {close} वर बंद झाला.",
              "gu": "સૌપ્રથમ બજારનો હાલ. નિફ્ટી 50 {pts} પોઈન્ટ એટલે કે {pct} ટકા {w:conj:d} {close} પર બંધ થયો."},
    "broad_item": {"en": "{idx} {w:moved:d} {p} percent", "hi": "{idx} {p} प्रतिशत {w:moved:d}", "ta": "{idx} {p} சதவீதம் {w:moved:d}",
                   "mr": "{idx} {p} टक्क्यांनी {w:moved:d}", "gu": "{idx} {p} ટકા {w:moved:d}"},
    "broad_flat": {"en": "{idx} was flat", "hi": "{idx} सपाट रहा", "ta": "{idx} மாற்றமின்றி இருந்தது", "mr": "{idx} सपाट राहिला", "gu": "{idx} સપાટ રહ્યો"},
    "breadth.strong": {"en": "Breadth was strong: {adv} Nifty 500 stocks rose, and {dec} fell.",
                       "hi": "बाज़ार की चौड़ाई मज़बूत रही: निफ्टी 500 के {adv} शेयर चढ़े और {dec} गिरे।",
                       "ta": "சந்தை பரவல் வலுவாக இருந்தது: நிஃப்டி 500-இல் {adv} பங்குகள் உயர்ந்தன, {dec} சரிந்தன.",
                       "mr": "बाजाराची व्याप्ती मजबूत होती: निफ्टी 500 मधील {adv} शेअर्स वाढले, तर {dec} घसरले.",
                       "gu": "બજારની પહોળાઈ મજબૂત રહી: નિફ્ટી 500ના {adv} શેરો વધ્યા અને {dec} ઘટ્યા."},
    "breadth.weak": {"en": "Breadth was weak: only {adv} Nifty 500 stocks rose, while {dec} fell.",
                     "hi": "बाज़ार की चौड़ाई कमज़ोर रही: निफ्टी 500 के सिर्फ़ {adv} शेयर चढ़े, जबकि {dec} गिरे।",
                     "ta": "சந்தை பரவல் பலவீனமாக இருந்தது: நிஃப்டி 500-இல் {adv} பங்குகள் மட்டுமே உயர்ந்தன, {dec} சரிந்தன.",
                     "mr": "बाजाराची व्याप्ती कमकुवत होती: निफ्टी 500 मधील फक्त {adv} शेअर्स वाढले, तर {dec} घसरले.",
                     "gu": "બજારની પહોળાઈ નબળી રહી: નિફ્ટી 500ના માત્ર {adv} શેરો વધ્યા, જ્યારે {dec} ઘટ્યા."},
    "breadth.mixed": {"en": "Breadth was mixed: {adv} Nifty 500 stocks rose and {dec} fell.",
                      "hi": "बाज़ार की चौड़ाई मिली-जुली रही: निफ्टी 500 के {adv} शेयर चढ़े और {dec} गिरे।",
                      "ta": "சந்தை பரவல் கலவையாக இருந்தது: நிஃப்டி 500-இல் {adv} பங்குகள் உயர்ந்தன, {dec} சரிந்தன.",
                      "mr": "बाजाराची व्याप्ती संमिश्र होती: निफ्टी 500 मधील {adv} शेअर्स वाढले, तर {dec} घसरले.",
                      "gu": "બજારની પહોળાઈ મિશ્ર રહી: નિફ્ટી 500ના {adv} શેરો વધ્યા અને {dec} ઘટ્યા."},
    "vix": {"en": "India VIX {w:eased:d} {p} percent, to {close}.", "hi": "इंडिया VIX {p} प्रतिशत {w:vixconj:d} {close} पर आ गया।",
            "ta": "இந்தியா VIX {p} சதவீதம் {w:vixconj:d} {close} ஆக இருந்தது.", "mr": "इंडिया VIX {p} टक्क्यांनी {w:vixconj:d} {close} वर आला.",
            "gu": "ઇન્ડિયા VIX {p} ટકા {w:vixconj:d} {close} પર આવ્યો."},
    "regime": {"en": "The desk's regime model reads {label}, with the trend {w:trend:t}.",
               "hi": "डेस्क का रेजीम मॉडल {w:regime:label} संकेत दे रहा है, और रुझान {w:trend:t} है।",
               "ta": "டெஸ்கின் சந்தை நிலை மாதிரி {w:regime:label} நிலையைக் காட்டுகிறது; போக்கு {w:trend:t}.",
               "mr": "डेस्कचे रेजीम मॉडेल {w:regime:label} स्थिती दाखवते, आणि कल {w:trend:t} आहे.",
               "gu": "ડેસ્કનું રેજીમ મોડલ {w:regime:label} સ્થિતિ બતાવે છે, અને વલણ {w:trend:t} છે."},
    # ---- s2 results
    "rw": {"en": "To earnings. The desk's Results Week tracker shows {declared} companies have declared this week.",
           "hi": "अब नतीजों की बात। डेस्क के रिज़ल्ट्स वीक ट्रैकर के मुताबिक इस हफ़्ते {declared} कंपनियों ने नतीजे घोषित किए हैं।",
           "ta": "இப்போது நிறுவன முடிவுகள். டெஸ்கின் ரிசல்ட்ஸ் வீக் டிராக்கரின்படி இந்த வாரம் {declared} நிறுவனங்கள் முடிவுகளை அறிவித்துள்ளன.",
           "mr": "आता निकालांविषयी. डेस्कच्या रिझल्ट्स वीक ट्रॅकरनुसार या आठवड्यात {declared} कंपन्यांनी निकाल जाहीर केले आहेत.",
           "gu": "હવે પરિણામોની વાત. ડેસ્કના રિઝલ્ટ્સ વીક ટ્રેકર મુજબ આ અઠવાડિયે {declared} કંપનીઓએ પરિણામ જાહેર કર્યા છે."},
    "rw_up": {"en": "To earnings. The desk's Results Week tracker shows {declared} companies have declared this week, with {upcoming} still to come.",
              "hi": "अब नतीजों की बात। डेस्क के रिज़ल्ट्स वीक ट्रैकर के मुताबिक इस हफ़्ते {declared} कंपनियों ने नतीजे घोषित किए हैं, और {upcoming} कंपनियों के नतीजे अभी आने बाकी हैं।",
              "ta": "இப்போது நிறுவன முடிவுகள். டெஸ்கின் ரிசல்ட்ஸ் வீக் டிராக்கரின்படி இந்த வாரம் {declared} நிறுவனங்கள் முடிவுகளை அறிவித்துள்ளன; மேலும் {upcoming} நிறுவனங்களின் முடிவுகள் இன்னும் வரவுள்ளன.",
              "mr": "आता निकालांविषयी. डेस्कच्या रिझल्ट्स वीक ट्रॅकरनुसार या आठवड्यात {declared} कंपन्यांनी निकाल जाहीर केले आहेत, तर {upcoming} कंपन्यांचे निकाल अजून यायचे आहेत.",
              "gu": "હવે પરિણામોની વાત. ડેસ્કના રિઝલ્ટ્સ વીક ટ્રેકર મુજબ આ અઠવાડિયે {declared} કંપનીઓએ પરિણામ જાહેર કર્યા છે, અને {upcoming} કંપનીઓના પરિણામ હજુ આવવાના બાકી છે."},
    "basis": {"en": "With no analyst consensus in the system, the desk scores each quarter against the company's own trend: {above} above, {in_line} in line, {below} below.",
              "hi": "सिस्टम में विश्लेषकों का अनुमान नहीं है, इसलिए डेस्क हर तिमाही की तुलना कंपनी के अपने रुझान से करता है: {above} उम्मीद से बेहतर, {in_line} उम्मीद के मुताबिक, और {below} उम्मीद से कमज़ोर।",
              "ta": "ஆய்வாளர் கணிப்பு அமைப்பில் இல்லாததால், டெஸ்க் ஒவ்வொரு காலாண்டையும் நிறுவனத்தின் சொந்தப் போக்குடன் ஒப்பிடுகிறது: {above} எதிர்பார்ப்பை விட சிறப்பு, {in_line} எதிர்பார்ப்புக்கு ஏற்ப, {below} எதிர்பார்ப்பை விடக் குறைவு.",
              "mr": "प्रणालीमध्ये विश्लेषकांचा अंदाज नसल्याने, डेस्क प्रत्येक तिमाहीची तुलना कंपनीच्या स्वतःच्या कलाशी करतो: {above} अपेक्षेपेक्षा चांगले, {in_line} अपेक्षेनुसार, आणि {below} अपेक्षेपेक्षा कमी.",
              "gu": "સિસ્ટમમાં વિશ્લેષકોનો અંદાજ ન હોવાથી, ડેસ્ક દરેક ત્રિમાસિકની સરખામણી કંપનીના પોતાના વલણ સાથે કરે છે: {above} અપેક્ષા કરતાં સારાં, {in_line} અપેક્ષા મુજબ, અને {below} અપેક્ષા કરતાં નબળાં."},
    "res_top": {"en": "{name} jumped {pct} percent", "hi": "{name} का शेयर {pct} प्रतिशत उछला", "ta": "{name} பங்கு {pct} சதவீதம் உயர்ந்தது",
                "mr": "{name} चा शेअर {pct} टक्क्यांनी उसळला", "gu": "{name}નો શેર {pct} ટકા ઉછળ્યો"},
    "res_top_vol": {"en": " on {volx} times its usual volume", "hi": ", कारोबार सामान्य से {volx} गुना रहा", "ta": ", வழக்கத்தை விட {volx} மடங்கு வர்த்தகத்துடன்",
                    "mr": ", सामान्यपेक्षा {volx} पट व्यवहारासह", "gu": ", સામાન્ય કરતાં {volx} ગણા વોલ્યૂમ સાથે"},
    "res_top_pat": {"en": ", after profit {w:grew:d} {pat} percent from a year ago", "hi": ", और तिमाही मुनाफ़ा साल-दर-साल {pat} प्रतिशत {w:patmoved:d}",
                    "ta": "; காலாண்டு லாபம் கடந்த ஆண்டை விட {pat} சதவீதம் {w:patmoved:d}", "mr": "; तिमाही नफा वर्षभरापूर्वीच्या तुलनेत {pat} टक्क्यांनी {w:patmoved:d}",
                    "gu": "; ત્રિમાસિક નફો ગયા વર્ષની સરખામણીએ {pat} ટકા {w:patmoved:d}"},
    "pct_item": {"en": "{name} {pct} percent", "hi": "{name} {pct} प्रतिशत", "ta": "{name} {pct} சதவீதம்", "mr": "{name} {pct} टक्क्यांनी", "gu": "{name} {pct} ટકા"},
    "pct_item_vol": {"en": "{name} {pct} percent on {volx} times its usual volume", "hi": "{name} {pct} प्रतिशत (सामान्य से {volx} गुना कारोबार)",
                     "ta": "{name} {pct} சதவீதம் (வழக்கத்தை விட {volx} மடங்கு வர்த்தகம்)", "mr": "{name} {pct} टक्क्यांनी (सामान्यपेक्षा {volx} पट व्यवहार)",
                     "gu": "{name} {pct} ટકા (સામાન્ય કરતાં {volx} ગણું વોલ્યૂમ)"},
    "pct_up": {"en": "{name} gained {pct} percent", "hi": "{name} {pct} प्रतिशत", "ta": "{name} {pct} சதவீதம்", "mr": "{name} {pct} टक्क्यांनी", "gu": "{name} {pct} ટકા"},
    "pct_dn": {"en": "{name} fell {pct} percent", "hi": "{name} {pct} प्रतिशत", "ta": "{name} {pct} சதவீதம்", "mr": "{name} {pct} टक्क्यांनी", "gu": "{name} {pct} ટકા"},
    "pct_dn_vol": {"en": "{name} fell {pct} percent on {volx} times its usual volume", "hi": "{name} {pct} प्रतिशत (सामान्य से {volx} गुना कारोबार)",
                   "ta": "{name} {pct} சதவீதம் (வழக்கத்தை விட {volx} மடங்கு வர்த்தகம்)", "mr": "{name} {pct} टक्क्यांनी (सामान्यपेक्षा {volx} पट व्यवहार)",
                   "gu": "{name} {pct} ટકા (સામાન્ય કરતાં {volx} ગણું વોલ્યૂમ)"},
    "res_more": {"en": "{items}.", "hi": "इसके अलावा {items} चढ़े।", "ta": "மேலும் {items} உயர்ந்தன.", "mr": "याशिवाय {items} वाढले.",
                 "gu": "આ ઉપરાંત {items} વધ્યા."},
    "res_down": {"en": "On the downside, {items}.", "hi": "गिरावट वाले शेयरों में {items} टूटे।", "ta": "சரிவில், {items} சரிந்தன.",
                 "mr": "घसरणीत, {items} घसरले.", "gu": "ઘટાડામાં, {items} તૂટ્યા."},
    "after_lead": {"en": "After the close, more results came in.", "hi": "बाज़ार बंद होने के बाद कुछ और कंपनियों ने नतीजे दिए।",
                   "ta": "சந்தை நிறைவுக்குப் பிறகு மேலும் சில நிறுவனங்கள் முடிவுகளை அறிவித்தன.", "mr": "बाजार बंद झाल्यानंतर आणखी काही कंपन्यांनी निकाल जाहीर केले.",
                   "gu": "બજાર બંધ થયા પછી કેટલીક વધુ કંપનીઓએ પરિણામ જાહેર કર્યા."},
    "after_first": {"en": "{name}'s profit rose {p} percent, to {pat} crore rupees", "hi": "{name} का मुनाफ़ा {p} प्रतिशत बढ़कर {pat} करोड़ रुपये रहा",
                    "ta": "{name} நிறுவனத்தின் லாபம் {p} சதவீதம் உயர்ந்து {pat} கோடி ரூபாயாக இருந்தது", "mr": "{name} चा नफा {p} टक्क्यांनी वाढून {pat} कोटी रुपये झाला",
                    "gu": "{name}નો નફો {p} ટકા વધીને {pat} કરોડ રૂપિયા રહ્યો"},
    "pat_item": {"en": "{name} {p} percent", "hi": "{name} ({p} प्रतिशत)", "ta": "{name} ({p} சதவீதம்)", "mr": "{name} ({p} टक्के)", "gu": "{name} ({p} ટકા)"},
    "after_more": {"en": "; profits also rose at {items}", "hi": "; {items} का मुनाफ़ा भी बढ़ा", "ta": "; {items} நிறுவனங்களின் லாபமும் உயர்ந்தது",
                   "mr": "; {items} यांचा नफाही वाढला", "gu": "; {items}નો નફો પણ વધ્યો"},
    "after_down": {"en": "Profit fell at {items}. They react on {dow}.", "hi": "वहीं {items} का मुनाफ़ा घटा। इन शेयरों पर असर {dow} को दिखेगा।",
                   "ta": "ஆனால் {items} நிறுவனங்களின் லாபம் குறைந்தது. இவற்றின் தாக்கம் {dow} அன்று தெரியும்.",
                   "mr": "मात्र {items} यांचा नफा घटला. याचा परिणाम {dow} रोजी दिसेल.", "gu": "જ્યારે {items}નો નફો ઘટ્યો. તેની અસર {dow}ના રોજ દેખાશે."},
    # ---- s3 sector rotation
    "rot_top": {"en": "Sector rotation now. {sector} led the indices, up {p} percent.", "hi": "अब सेक्टर रोटेशन। {sector} {p} प्रतिशत चढ़कर सबसे आगे रहा।",
                "ta": "இப்போது துறை சுழற்சி. {sector} {p} சதவீதம் உயர்ந்து முன்னிலை வகித்தது.", "mr": "आता सेक्टर रोटेशन. {sector} {p} टक्क्यांनी वाढून आघाडीवर राहिला.",
                "gu": "હવે સેક્ટર રોટેશન. {sector} {p} ટકા વધીને સૌથી આગળ રહ્યું."},
    "rot_follow": {"en": " Then came {names}.", "hi": " उसके बाद {names} रहे।", "ta": " அதைத் தொடர்ந்து {names}.", "mr": " त्यानंतर {names}.",
                   "gu": " ત્યાર બાદ {names}."},
    "rot_weak": {"en": "{sector} was the weakest, down {p} percent.", "hi": "{sector} सबसे कमज़ोर रहा, {p} प्रतिशत नीचे।",
                 "ta": "{sector} மிகவும் பலவீனமாக இருந்தது, {p} சதவீதம் சரிவு.", "mr": "{sector} सर्वात कमकुवत ठरला, {p} टक्क्यांनी खाली.",
                 "gu": "{sector} સૌથી નબળું રહ્યું, {p} ટકા નીચે."},
    "rot_weak_n": {"en": " {dec} of its {n} stocks ended in the red.", "hi": " इसके {n} में से {dec} शेयर लाल निशान में रहे।",
                   "ta": " அதன் {n} பங்குகளில் {dec} சிவப்பில் முடிந்தன.", "mr": " त्यातील {n} पैकी {dec} शेअर्स लाल निशाणीत राहिले.",
                   "gu": " તેના {n}માંથી {dec} શેરો લાલ નિશાનમાં રહ્યા."},
    "rot_month": {"en": "Over a month, {hi} is {w:dir:dh} {phi} percent, while {lo} is {w:dir:dl} {plo} percent.",
                  "hi": "एक महीने में {hi} में {phi} प्रतिशत की {w:chg:dh} है, जबकि {lo} में {plo} प्रतिशत की {w:chg:dl} है।",
                  "ta": "ஒரு மாத அளவில் {hi} {phi} சதவீதம் {w:chg:dh} கண்டுள்ளது, {lo} {plo} சதவீதம் {w:chg:dl} கண்டுள்ளது.",
                  "mr": "महिनाभरात {hi} मध्ये {phi} टक्क्यांची {w:chg:dh} आहे, तर {lo} मध्ये {plo} टक्क्यांची {w:chg:dl} आहे.",
                  "gu": "એક મહિનામાં {hi}માં {phi} ટકાનો {w:chg:dh} છે, જ્યારે {lo}માં {plo} ટકાનો {w:chg:dl} છે."},
    "rot_leading": {"en": " The desk's rotation matrix tags {names} as leading.", "hi": " डेस्क का रोटेशन मैट्रिक्स {names} को आगे बता रहा है।",
                    "ta": " டெஸ்கின் சுழற்சி அட்டவணை {names} துறைகளை முன்னணியில் காட்டுகிறது.", "mr": " डेस्कचा रोटेशन मॅट्रिक्स {names} यांना आघाडीवर दाखवतो.",
                    "gu": " ડેસ્કનું રોટેશન મેટ્રિક્સ {names}ને આગળ બતાવે છે."},
    # ---- s4 movers
    "mv_intro": {"en": "Movers and shakers, index by index. ", "hi": "अब इंडेक्स-दर-इंडेक्स बड़े मूवर्स। ", "ta": "இப்போது குறியீடு வாரியாக முக்கிய நகர்வுகள். ",
                 "mr": "आता निर्देशांकनिहाय मोठ्या हालचाली. ", "gu": "હવે ઇન્ડેક્સ મુજબ મોટા મૂવર્સ. "},
    "mv_head": {"en": "In the {idx}, {adv} stocks rose and {dec} fell.", "hi": "{idx} में {adv} शेयर चढ़े और {dec} गिरे।",
                "ta": "{idx}-இல் {adv} பங்குகள் உயர்ந்தன, {dec} சரிந்தன.", "mr": "{idx} मध्ये {adv} शेअर्स वाढले, तर {dec} घसरले.",
                "gu": "{idx}માં {adv} શેરો વધ્યા અને {dec} ઘટ્યા."},
    "mv_ups": {"en": " Gainers: {items}.", "hi": " बढ़त में: {items}।", "ta": " உயர்வில் {items}.", "mr": " वाढीत {items}.", "gu": " વધારામાં {items}."},
    "mv_downs": {"en": " Losers: {items}.", "hi": " गिरावट में: {items}।", "ta": " சரிவில் {items}.", "mr": " घसरणीत {items}.", "gu": " ઘટાડામાં {items}."},
    "sec_intro": {"en": "By sector: {items}.", "hi": "सेक्टर के हिसाब से: {items}।", "ta": "துறை வாரியாக: {items}.", "mr": "क्षेत्रनिहाय: {items}.", "gu": "સેક્ટર મુજબ: {items}."},
    "sec_full": {"en": "every {sector} stock in the 500 rose", "hi": "निफ्टी 500 में {sector} के सभी शेयर चढ़े",
                 "ta": "நிஃப்டி 500-இல் {sector} துறையின் அனைத்துப் பங்குகளும் உயர்ந்தன", "mr": "निफ्टी 500 मधील {sector} क्षेत्रातील सर्व शेअर्स वाढले",
                 "gu": "નિફ્ટી 500માં {sector}ના બધા શેરો વધ્યા"},
    "sec_worst": {"en": "{sector} managed just {adv} of {n} gainers", "hi": "{sector} के {n} में से सिर्फ़ {adv} शेयर चढ़े",
                  "ta": "{sector} துறையின் {n} பங்குகளில் {adv} மட்டுமே உயர்ந்தன", "mr": "{sector} क्षेत्रातील {n} पैकी फक्त {adv} शेअर्स वाढले",
                  "gu": "{sector}ના {n}માંથી માત્ર {adv} શેરો વધ્યા"},
    # ---- s5 flows
    "flows_fii": {"en": "Follow the money. Provisional data show FIIs {w:bought:b} a net {fii} crore rupees in cash {when}.",
                  "hi": "अब पैसे का प्रवाह। प्रोविज़नल आंकड़ों के मुताबिक {when} FII ने कैश में {fii} करोड़ रुपये की शुद्ध {w:net:b} की।",
                  "ta": "இப்போது பண ஓட்டம். தற்காலிகத் தரவுகளின்படி {when} FII-கள் ரொக்கச் சந்தையில் {fii} கோடி ரூபாய்க்கு நிகர {w:net:b} செய்தனர்.",
                  "mr": "आता पैशाचा ओघ. प्रोव्हिजनल आकडेवारीनुसार {when} FII नी रोख बाजारात {fii} कोटी रुपयांची निव्वळ {w:net:b} केली.",
                  "gu": "હવે નાણાંનો પ્રવાહ. પ્રોવિઝનલ આંકડા મુજબ {when} FII એ રોકડ બજારમાં {fii} કરોડ રૂપિયાની ચોખ્ખી {w:net:b} કરી."},
    "flows_since": {"en": " It was their biggest {w:buying:b} day since {since}.", "hi": " यह {since} के बाद उनकी {w:net:b} का सबसे बड़ा दिन है।",
                    "ta": " இது {since} க்குப் பிறகு அவர்களின் மிகப்பெரிய {w:net:b} நாள்.", "mr": " {since} नंतरचा हा त्यांचा {w:net_of:b} सर्वात मोठा दिवस आहे.",
                    "gu": " {since} પછીનો આ તેમનો {w:net_of:b} સૌથી મોટો દિવસ છે."},
    "flows_dii": {"en": " DIIs {w:bought:db} {dii} crore.", "hi": " DII ने {dii} करोड़ रुपये की {w:net:db} की।", "ta": " DII-கள் {dii} கோடி ரூபாய்க்கு {w:net:db} செய்தனர்.",
                  "mr": " DII नी {dii} कोटी रुपयांची {w:net:db} केली.", "gu": " DII એ {dii} કરોડ રૂપિયાની {w:net:db} કરી."},
    "today": {"en": "today", "hi": "आज", "ta": "இன்று", "mr": "आज", "gu": "આજે"},
    "on_date": {"en": "on {date}", "hi": "{date} को", "ta": "{date} அன்று", "mr": "{date} रोजी", "gu": "{date}ના રોજ"},
    "mtd": {"en": "For {month} so far, FIIs are net {w:buyers:b1} of {f1} crore, and DIIs net {w:buyers:b2} of {f2} crore.",
            "hi": "{month} में अब तक FII ने {f1} करोड़ की शुद्ध {w:net:b1} की है, और DII ने {f2} करोड़ की शुद्ध {w:net:b2} की है।",
            "ta": "{month} மாதத்தில் இதுவரை FII-கள் {f1} கோடி நிகர {w:net:b1}, DII-கள் {f2} கோடி நிகர {w:net:b2} செய்துள்ளனர்.",
            "mr": "{month} महिन्यात आतापर्यंत FII नी {f1} कोटींची निव्वळ {w:net:b1} केली आहे, तर DII नी {f2} कोटींची निव्वळ {w:net:b2} केली आहे.",
            "gu": "{month}માં અત્યાર સુધી FII એ {f1} કરોડની ચોખ્ખી {w:net:b1} કરી છે, અને DII એ {f2} કરોડની ચોખ્ખી {w:net:b2} કરી છે."},
    "m3": {"en": " Over three months, FIIs have {w:bought:b3} {f3} crore, and DIIs {w:bought:b4} {f4} crore.",
           "hi": " तीन महीनों में FII ने {f3} करोड़ की {w:net:b3} की है, और DII ने {f4} करोड़ की {w:net:b4}।",
           "ta": " மூன்று மாதங்களில் FII-கள் {f3} கோடி {w:net:b3}, DII-கள் {f4} கோடி {w:net:b4} செய்துள்ளனர்.",
           "mr": " तीन महिन्यांत FII नी {f3} कोटींची {w:net:b3} केली, तर DII नी {f4} कोटींची {w:net:b4} केली.",
           "gu": " ત્રણ મહિનામાં FII એ {f3} કરોડની {w:net:b3} કરી, અને DII એ {f4} કરોડની {w:net:b4} કરી."},
    "flow_chart": {"en": "The desk's flow chart runs to {date}; today's figures join with the next load. One day of flows is a signal, not yet a trend.",
                   "hi": "डेस्क का फ्लो चार्ट {date} तक का है; आज के आंकड़े अगले अपडेट में जुड़ेंगे। एक दिन का प्रवाह संकेत है, अभी रुझान नहीं।",
                   "ta": "டெஸ்கின் பண ஓட்ட வரைபடம் {date} வரை உள்ளது; இன்றைய தரவு அடுத்த புதுப்பிப்பில் சேரும். ஒரு நாள் பண ஓட்டம் ஒரு சமிக்ஞை மட்டுமே, இன்னும் போக்கு அல்ல.",
                   "mr": "डेस्कचा फ्लो चार्ट {date} पर्यंतचा आहे; आजचे आकडे पुढील अपडेटमध्ये जोडले जातील. एका दिवसाचा ओघ हा संकेत आहे, अजून कल नाही.",
                   "gu": "ડેસ્કનો ફ્લો ચાર્ટ {date} સુધીનો છે; આજના આંકડા આગામી અપડેટમાં ઉમેરાશે. એક દિવસનો પ્રવાહ સંકેત છે, હજુ વલણ નથી."},
    "flow_signal": {"en": "One day of flows is a signal, not yet a trend.", "hi": "एक दिन का प्रवाह संकेत है, अभी रुझान नहीं।",
                    "ta": "ஒரு நாள் பண ஓட்டம் ஒரு சமிக்ஞை மட்டுமே, இன்னும் போக்கு அல்ல.", "mr": "एका दिवसाचा ओघ हा संकेत आहे, अजून कल नाही.",
                    "gu": "એક દિવસનો પ્રવાહ સંકેત છે, હજુ વલણ નથી."},
    # ---- s6 ideas
    "ideas_intro": {"en": "Now, the desk's Top 10 ideas. These are ideas for review, not recommendations, and the desk's own scorecard shows no measurable ranking skill yet.",
                    "hi": "अब डेस्क के टॉप 10 आइडिया। ये समीक्षा के लिए आइडिया हैं, सिफ़ारिशें नहीं, और डेस्क के अपने स्कोरकार्ड में अभी रैंकिंग की कोई मापने योग्य क्षमता नहीं दिखी है।",
                    "ta": "இப்போது டெஸ்கின் டாப் 10 யோசனைகள். இவை பரிசீலனைக்கான யோசனைகள் மட்டுமே, பரிந்துரைகள் அல்ல; டெஸ்கின் சொந்த மதிப்பீட்டில் இன்னும் அளவிடக்கூடிய தரவரிசைத் திறன் தெரியவில்லை.",
                    "mr": "आता डेस्कच्या टॉप 10 कल्पना. या आढाव्यासाठीच्या कल्पना आहेत, शिफारसी नाहीत, आणि डेस्कच्या स्वतःच्या स्कोअरकार्डमध्ये अजून मोजता येईल अशी क्रमवारी क्षमता दिसलेली नाही.",
                    "gu": "હવે ડેસ્કના ટોપ 10 આઇડિયા. આ સમીક્ષા માટેના આઇડિયા છે, ભલામણો નહીં, અને ડેસ્કના પોતાના સ્કોરકાર્ડમાં હજુ માપી શકાય તેવી રેન્કિંગ ક્ષમતા દેખાઈ નથી."},
    "ideas_lead": {"en": "{names} lead the cash list.", "hi": "कैश लिस्ट में {names} सबसे ऊपर हैं।", "ta": "ரொக்கப் பட்டியலில் {names} முன்னணியில் உள்ளன.",
                   "mr": "कॅश यादीत {names} आघाडीवर आहेत.", "gu": "કેશ યાદીમાં {names} ટોચ પર છે."},
    "ideas_why": {"en": " {name}: {why}.", "hi": "", "ta": "", "mr": "", "gu": ""},
    "ideas_rest": {"en": "{names} complete the list.", "hi": "{names} भी इस सूची में हैं।", "ta": "{names} ஆகியவையும் இந்தப் பட்டியலில் உள்ளன.",
                   "mr": "{names} यांचाही या यादीत समावेश आहे.", "gu": "{names} પણ આ યાદીમાં છે."},
    "fno": {"en": "The F and O board reads a {w:regime:label} regime with a {w:trend:t} trend, so it fits defined-risk structures, like the {sym} {strategy} for {expiry}.",
            "hi": "एफ़ एंड ओ बोर्ड {w:regime:label} रेजीम और {w:trend:t} रुझान दिखा रहा है, इसलिए यह सीमित जोखिम वाली रणनीतियाँ सुझाता है, जैसे {expiry} एक्सपायरी का {sym} {strategy}।",
            "ta": "எஃப் அண்ட் ஓ பலகை {w:regime:label} நிலையையும் {w:trend:t} போக்கையும் காட்டுகிறது; எனவே வரையறுக்கப்பட்ட இடர் கொண்ட உத்திகள் பொருந்துகின்றன, உதாரணமாக {expiry} காலாவதியாகும் {sym} {strategy}.",
            "mr": "एफ अँड ओ बोर्ड {w:regime:label} रेजीम आणि {w:trend:t} कल दाखवतो, म्हणून मर्यादित जोखमीच्या रणनीती योग्य ठरतात, उदाहरणार्थ {expiry} एक्स्पायरीचा {sym} {strategy}.",
            "gu": "એફ એન્ડ ઓ બોર્ડ {w:regime:label} રેજીમ અને {w:trend:t} વલણ બતાવે છે, તેથી મર્યાદિત જોખમવાળી વ્યૂહરચનાઓ યોગ્ય છે, જેમ કે {expiry} એક્સપાયરીનો {sym} {strategy}."},
    "fno_conflict": {"en": " The desk shows these for information only where they conflict with bullish cash setups.",
                     "hi": " जहाँ ये कैश के तेज़ी वाले सेटअप से टकराते हैं, वहाँ डेस्क इन्हें सिर्फ़ जानकारी के लिए दिखाता है।",
                     "ta": " ரொக்கச் சந்தையின் ஏற்ற அமைப்புகளுடன் முரண்படும் இடங்களில், டெஸ்க் இவற்றைத் தகவலுக்காக மட்டுமே காட்டுகிறது.",
                     "mr": " जिथे या कॅशमधील तेजीच्या सेटअपशी विसंगत आहेत, तिथे डेस्क त्या फक्त माहितीसाठी दाखवतो.",
                     "gu": " જ્યાં તે કેશના તેજીના સેટઅપ સાથે વિરોધાભાસી છે, ત્યાં ડેસ્ક તેને માત્ર માહિતી માટે બતાવે છે."},
    # ---- s7 what to watch
    "watch_macro": {"en": "{dow}: {items}.", "hi": "{dow} को: {items}।", "ta": "{dow}: {items}.", "mr": "{dow} रोजी: {items}.", "gu": "{dow}ના રોજ: {items}."},
    "macro_item": {"en": "{event} at {time} India time", "hi": "भारतीय समय {time} {event}", "ta": "இந்திய நேரப்படி {time} {event}",
                   "mr": "भारतीय वेळेनुसार {time} {event}", "gu": "ભારતીય સમય મુજબ {time} {event}"},
    "watch_both": {"en": "{lead}reactions to {react}, and results from {due}.", "hi": "{lead}{react} के शेयरों की प्रतिक्रिया, और {due} के नतीजे।",
                   "ta": "{lead}{react} பங்குகளின் எதிர்வினை, மற்றும் {due} நிறுவனங்களின் முடிவுகள்.", "mr": "{lead}{react} यांच्या शेअर्सची प्रतिक्रिया, आणि {due} यांचे निकाल.",
                   "gu": "{lead}{react}ના શેરોની પ્રતિક્રિયા, અને {due}ના પરિણામો."},
    "watch_react": {"en": "{lead}reactions to {react}.", "hi": "{lead}{react} के शेयरों की प्रतिक्रिया।", "ta": "{lead}{react} பங்குகளின் எதிர்வினை.",
                    "mr": "{lead}{react} यांच्या शेअर्सची प्रतिक्रिया.", "gu": "{lead}{react}ના શેરોની પ્રતિક્રિયા."},
    "watch_due": {"en": "{lead}results from {due}.", "hi": "{lead}{due} के नतीजे।", "ta": "{lead}{due} நிறுவனங்களின் முடிவுகள்.", "mr": "{lead}{due} यांचे निकाल.",
                  "gu": "{lead}{due}ના પરિણામો."},
    "plus": {"en": "Plus ", "hi": "साथ ही ", "ta": "மேலும் ", "mr": "तसेच ", "gu": "ઉપરાંત "},
    "dow_lead": {"en": "{dow}: ", "hi": "{dow} को: ", "ta": "{dow}: ", "mr": "{dow} रोजी: ", "gu": "{dow}ના રોજ: "},
    "signoff.0": {"en": "That's Closing Bell from the Nivesh Desk.", "hi": "निवेश डेस्क से क्लोज़िंग बेल में आज बस इतना ही।",
                  "ta": "நிவேஷ் டெஸ்கின் க்ளோசிங் பெல் இத்துடன் நிறைவடைகிறது.", "mr": "निवेश डेस्कवरून क्लोजिंग बेल आज इथेच संपते.",
                  "gu": "નિવેશ ડેસ્ક પરથી ક્લોઝિંગ બેલ આજે અહીં પૂરું થાય છે."},
    "signoff.1": {"en": "And that's Closing Bell for today, from the Nivesh Desk."},
    "disclaimer": {"en": "Market information and education, not investment advice. Good night.",
                   "hi": "यह बाज़ार की जानकारी और शिक्षा है, निवेश सलाह नहीं। शुभ रात्रि।",
                   "ta": "இது சந்தைத் தகவலும் கல்வியும் மட்டுமே, முதலீட்டு ஆலோசனை அல்ல. இனிய இரவு.",
                   "mr": "ही बाजाराची माहिती आणि शिक्षण आहे, गुंतवणूक सल्ला नाही. शुभ रात्री.",
                   "gu": "આ બજારની માહિતી અને શિક્ષણ છે, રોકાણ સલાહ નથી. શુભ રાત્રિ."},
}


# ------------------------------------------------------------------------------------------------ rendering
def tmpl(key: str, lang: str) -> str:
    """Template for a key; numbered English-only variants (welcome.2) fall back to the base key elsewhere."""
    t = T.get(key, {})
    if lang in t:
        return t[lang]
    base = key.rsplit(".", 1)[0]
    if base != key and lang in T.get(base, {}):
        return T[base][lang]
    if lang != "en" and key.startswith("signoff."):
        return T["signoff.0"][lang]
    raise KeyError(f"no template {key} for {lang}")


def word(lang: str, name: str, value: str) -> str:
    table = WORDS[lang].get(name) or {}
    return table.get(value, value)


def render(lang: str, key: str, args: Dict[str, Any]) -> str:
    def sub(m: re.Match) -> str:
        expr = m.group(1)
        if expr.startswith("w:"):
            _, name, arg = expr.split(":")
            return word(lang, name, str(args[arg]))
        v = args[expr]
        return localize(lang, v)
    return re.sub(r"\{([^{}]+)\}", sub, tmpl(key, lang))


def localize(lang: str, v: Any) -> str:
    """Arguments: plain strings (already-formatted numbers, names), or tagged dicts rendered per language."""
    if isinstance(v, dict):
        kind = v.get("k")
        if kind == "date":
            d = date.fromisoformat(v["iso"][:10])
            m = MONTHS[lang][d.month - 1]
            return f"{m} {d.day}" if lang == "ta" else f"{d.day} {m}"
        if kind == "month":
            return MONTHS[lang][int(v["m"]) - 1]
        if kind == "dow":
            return WEEKDAYS[lang][date.fromisoformat(v["iso"][:10]).weekday()]
        if kind == "index":
            return v["en"] if lang == "en" else (INDEX_NAMES.get(v["en"], {}).get(lang) or v["en"].replace("the ", ""))
        if kind == "time":
            return spoken_time(lang, v["hhmm"])
        if kind == "macro":
            return macro_name(lang, v)
        if kind == "list":
            return join_list(lang, [localize(lang, x) for x in v["items"]])
        if kind == "msg":
            return render(lang, v["key"], v["args"])
        if kind == "raw":
            return v["s"]
        raise ValueError(f"unknown arg kind {kind}")
    return str(v)


def join_list(lang: str, items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return items[0] if items else ""
    if lang == "en":
        return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]
    return ", ".join(items[:-1]) + f" {AND[lang]} " + items[-1]


def spoken_time(lang: str, hhmm: str) -> str:
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    h12 = h % 12 or 12
    clock = f"{h12}:{m:02d}" if m else f"{h12}"
    if lang == "en":
        return f"{clock} {'AM' if h < 12 else 'PM'}"
    part = ("morning" if 5 <= h < 12 else "noon" if 12 <= h < 16 else "evening" if 16 <= h < 20 else "night")
    P = {"hi": {"morning": "सुबह", "noon": "दोपहर", "evening": "शाम", "night": "रात"},
         "ta": {"morning": "காலை", "noon": "மதியம்", "evening": "மாலை", "night": "இரவு"},
         "mr": {"morning": "सकाळी", "noon": "दुपारी", "evening": "सायंकाळी", "night": "रात्री"},
         "gu": {"morning": "સવારે", "noon": "બપોરે", "evening": "સાંજે", "night": "રાત્રે"}}[lang][part]
    suffix = {"hi": "बजे", "ta": "மணிக்கு", "mr": "वाजता", "gu": "વાગ્યે"}[lang]
    return f"{P} {clock} {suffix}"


def macro_name(lang: str, v: Dict[str, Any]) -> str:
    code, name, country = v.get("code") or "", v.get("name") or "", v.get("country")
    if lang == "en":
        clean = name.replace("YoY", "").strip()
        return f"India's {clean.lower()} data" if country == "IN" else f"the US {clean}"
    return (MACRO.get(code) or {}).get(lang) or name


def spoken(lang: str, text: str) -> str:
    """Narration fixes for the voice: symbols read aloud, ranges like 22350/22750 as words."""
    t = text.replace("&", " and " if lang == "en" else " एंड " if lang in ("hi", "mr") else " அண்ட் " if lang == "ta" else " એન્ડ ")
    t = t.replace("₹", "").replace("×", " times" if lang == "en" else "")
    if lang == "en":
        t = t.replace("%", " percent")
        t = re.sub(r"\bavg\b", "average", t)
        t = re.sub(r"\bDMA\b", "day average", t)
    t = re.sub(r"(\d)/(\d)", lambda m: m.group(1) + RANGE[lang] + m.group(2), t)
    return re.sub(r"\s{2,}", " ", t).strip()
