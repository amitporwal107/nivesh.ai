"""Opening Bell — sentence templates for the morning edition, in English, Hindi, Tamil, Marathi and Gujarati.

Same rules as i18n.py (owner decision 2026-10-28): fixed templates translated once, only numbers, names and
dates filled in each morning, every number traced by script_gen.Facts. Importing this module adds the keys to
i18n.T / i18n.WORDS / i18n.SECTION_TITLES; the Closing Bell's own keys are not changed.
The Top 10 idea sentences (idea.*), the F&O board lines, broad-index items, FII/DII lines and macro items are
shared with the Closing Bell.
NOTE: the Tamil, Marathi and Gujarati wording should get one native-speaker review, like the evening's.
"""
from __future__ import annotations

import i18n

# phrases checks.py requires in every language of the morning edition, besides i18n.REQUIRED
REQUIRED_OPEN = {"en": ["not forecasts"], "hi": ["पूर्वानुमान नहीं"], "ta": ["முன்னறிவிப்புகள் அல்ல"], "mr": ["अंदाज नाहीत"], "gu": ["આગાહી નથી"]}

WORDS = {
    "en": {"ind": {"up": "higher", "down": "lower"}},
    "hi": {"ind": {"up": "ऊपर", "down": "नीचे"}},
    "ta": {"ind": {"up": "அதிகம்", "down": "குறைவு"}},
    "mr": {"ind": {"up": "जास्त", "down": "कमी"}},
    "gu": {"ind": {"up": "ઉપર", "down": "નીચે"}},
}

SECTION_TITLES = {
    "PREVIOUS SESSION": {"hi": ("पिछला सत्र", "पिछला बंद और रात की हलचल"), "ta": ("முந்தைய அமர்வு", "முந்தைய முடிவும் இரவு நகர்வுகளும்"),
                         "mr": ("मागील सत्र", "मागील बंद आणि रात्रीच्या हालचाली"), "gu": ("ગયું સત્ર", "ગયો બંધ અને રાતની હલચલ")},
    "PRE-OPEN": {"hi": ("प्री-ओपन", "प्री-ओपन क्या कहता है"), "ta": ("ப்ரீ-ஓப்பன்", "ப்ரீ-ஓப்பன் என்ன சொல்கிறது"),
                 "mr": ("प्री-ओपन", "प्री-ओपन काय सांगतो"), "gu": ("પ્રી-ઓપન", "પ્રી-ઓપન શું કહે છે")},
    "RANGES & LEVELS": {"hi": ("रेंज और लेवल", "ऑप्शंस बाज़ार से रेंज और लेवल"), "ta": ("வரம்புகளும் நிலைகளும்", "ஆப்ஷன் சந்தையிலிருந்து வரம்புகளும் நிலைகளும்"),
                        "mr": ("रेंज आणि लेव्हल", "ऑप्शन्स बाजारातून रेंज आणि लेव्हल"), "gu": ("રેન્જ અને લેવલ", "ઓપ્શન્સ બજારમાંથી રેન્જ અને લેવલ")},
    "TODAY": {"hi": ("आज", None), "ta": ("இன்று", None), "mr": ("आज", None), "gu": ("આજે", None)},
}

T = {
    # ---- s0 headlines
    "o_welcome.0": {"en": "Good morning, and welcome to the Opening Bell on the Nivesh Desk."},
    "o_welcome.1": {"en": "Good morning. This is the Opening Bell, from the Nivesh Desk."},
    "o_welcome.2": {"en": "Good morning, and welcome to the Opening Bell on the Nivesh Desk, your set-up for the session ahead."},
    "o_welcome": {"hi": "सुप्रभात, निवेश डेस्क से ओपनिंग बेल में आपका स्वागत है।",
                  "ta": "காலை வணக்கம், நிவேஷ் டெஸ்கின் ஓப்பனிங் பெல் நிகழ்ச்சிக்கு உங்களை வரவேற்கிறோம்.",
                  "mr": "सुप्रभात, निवेश डेस्कवरील ओपनिंग बेलमध्ये आपले स्वागत आहे.",
                  "gu": "સુપ્રભાત, નિવેશ ડેસ્ક પરથી ઓપનિંગ બેલમાં આપનું સ્વાગત છે."},
    "o_heads": {"en": "Here's what's set up for today.", "hi": "आज के सत्र की मुख्य बातें।", "ta": "இன்றைய வர்த்தகத்துக்கான முக்கிய அம்சங்கள்.",
                "mr": "आजच्या सत्रातील ठळक मुद्दे.", "gu": "આજના સત્રના મુખ્ય મુદ્દા."},
    "oh_pre.up": {"en": "The pre-open points to a higher start, with the Nifty indicated near {lvl}.",
                  "hi": "प्री-ओपन ऊँची शुरुआत का संकेत दे रहा है, निफ्टी {lvl} के आसपास संकेतित है।",
                  "ta": "ப்ரீ-ஓப்பன் உயர்வான தொடக்கத்தைக் காட்டுகிறது; நிஃப்டி சுமார் {lvl} அளவில் உள்ளது.",
                  "mr": "प्री-ओपन वाढीव सुरुवातीचे संकेत देत आहे, निफ्टी सुमारे {lvl} वर दिसत आहे.",
                  "gu": "પ્રી-ઓપન ઊંચી શરૂઆતનો સંકેત આપે છે, નિફ્ટી આશરે {lvl} પર દેખાય છે."},
    "oh_pre.down": {"en": "The pre-open points to a lower start, with the Nifty indicated near {lvl}.",
                    "hi": "प्री-ओपन कमज़ोर शुरुआत का संकेत दे रहा है, निफ्टी {lvl} के आसपास संकेतित है।",
                    "ta": "ப்ரீ-ஓப்பன் சரிவான தொடக்கத்தைக் காட்டுகிறது; நிஃப்டி சுமார் {lvl} அளவில் உள்ளது.",
                    "mr": "प्री-ओपन घसरणीच्या सुरुवातीचे संकेत देत आहे, निफ्टी सुमारे {lvl} वर दिसत आहे.",
                    "gu": "પ્રી-ઓપન નબળી શરૂઆતનો સંકેત આપે છે, નિફ્ટી આશરે {lvl} પર દેખાય છે."},
    "oh_pre.flat": {"en": "The pre-open points to a flat start, with the Nifty indicated near {lvl}.",
                    "hi": "प्री-ओपन सपाट शुरुआत का संकेत दे रहा है, निफ्टी {lvl} के आसपास है।",
                    "ta": "ப்ரீ-ஓப்பன் மாற்றமில்லாத தொடக்கத்தைக் காட்டுகிறது; நிஃப்டி சுமார் {lvl} அளவில் உள்ளது.",
                    "mr": "प्री-ओपन सपाट सुरुवातीचे संकेत देत आहे, निफ्टी सुमारे {lvl} वर आहे.",
                    "gu": "પ્રી-ઓપન સપાટ શરૂઆતનો સંકેત આપે છે, નિફ્ટી આશરે {lvl} પર છે."},
    "oh_pre.wait": {"en": "The pre-open prices land at eight minutes past nine.",
                    "hi": "प्री-ओपन के भाव नौ बजकर आठ मिनट पर आते हैं।",
                    "ta": "ப்ரீ-ஓப்பன் விலைகள் ஒன்பது மணி எட்டு நிமிடத்துக்கு வரும்.",
                    "mr": "प्री-ओपनचे भाव नऊ वाजून आठ मिनिटांनी येतात.",
                    "gu": "પ્રી-ઓપનના ભાવ નવ વાગીને આઠ મિનિટે આવે છે."},
    "oh_range": {"en": "India VIX prices a typical day of about {pts} points either way: {lo} to {hi} on the Nifty.",
                 "hi": "इंडिया VIX के हिसाब से आज निफ्टी में दोनों तरफ़ करीब {pts} अंकों की सामान्य चाल: {lo} से {hi}।",
                 "ta": "இந்தியா VIX படி நிஃப்டியில் இரு பக்கமும் சுமார் {pts} புள்ளிகள் வழக்கமான நகர்வு: {lo} முதல் {hi} வரை.",
                 "mr": "इंडिया VIX नुसार आज निफ्टीत दोन्ही बाजूंना सुमारे {pts} अंकांची सर्वसाधारण हालचाल: {lo} ते {hi}.",
                 "gu": "ઇન્ડિયા VIX મુજબ આજે નિફ્ટીમાં બંને તરફ આશરે {pts} પોઇન્ટની સામાન્ય ચાલ: {lo} થી {hi}."},
    "oh_ai": {"en": "On the desk's AI list, {names} lead today's Top 10 ideas.",
              "hi": "डेस्क की AI लिस्ट में आज के टॉप 10 आइडिया में {names} सबसे आगे हैं।",
              "ta": "டெஸ்கின் AI பட்டியலில் இன்றைய டாப் 10 யோசனைகளில் {names} முன்னணியில் உள்ளன.",
              "mr": "डेस्कच्या AI यादीत आजच्या टॉप 10 कल्पनांमध्ये {names} आघाडीवर आहेत.",
              "gu": "ડેસ્કની AI યાદીમાં આજના ટોપ 10 આઇડિયામાં {names} ટોચ પર છે."},
    "oh_expiry": {"en": "And it's Nifty expiry day.", "hi": "और आज निफ्टी की एक्सपायरी है।", "ta": "இன்று நிஃப்டி காலாவதி நாள்.",
                  "mr": "आणि आज निफ्टीची एक्स्पायरी आहे.", "gu": "અને આજે નિફ્ટીની એક્સપાયરી છે."},
    "oh_results": {"en": "On today's results calendar: {names}.", "hi": "आज के नतीजों के कैलेंडर में: {names}।",
                   "ta": "இன்றைய முடிவுகள் அட்டவணையில்: {names}.", "mr": "आजच्या निकालांच्या कॅलेंडरमध्ये: {names}.",
                   "gu": "આજના પરિણામોના કેલેન્ડરમાં: {names}."},
    # ---- previous session
    "o_recap": {"en": "First, where we left off. On {dow}, the Nifty 50 closed at {close}, {w:dir:d} {pts} points, or {pct} percent.",
                "hi": "पहले, पिछले सत्र का हाल। {dow} को निफ्टी 50 {pts} अंक यानी {pct} प्रतिशत {w:conj:d} {close} पर बंद हुआ।",
                "ta": "முதலில், கடந்த அமர்வு. {dow} அன்று நிஃப்டி 50 {pts} புள்ளிகள், அதாவது {pct} சதவீதம் {w:conj:d} {close} புள்ளிகளில் நிறைவடைந்தது.",
                "mr": "आधी, मागच्या सत्राचा आढावा. {dow} रोजी निफ्टी 50 {pts} अंकांनी, म्हणजे {pct} टक्क्यांनी {w:conj:d} {close} वर बंद झाला.",
                "gu": "પહેલાં, ગયા સત્રનો હાલ. {dow}ના રોજ નિફ્ટી 50 {pts} પોઇન્ટ, એટલે કે {pct} ટકા {w:conj:d} {close} પર બંધ થયો."},
    "o_mcx": {"en": "On MCX last night, crude oil ended at {crude} rupees a barrel, {w:dir:d1} {p1} percent, and gold at {gold} rupees for ten grams, {w:dir:d2} {p2} percent.",
              "hi": "MCX पर कल रात कच्चा तेल {p1} प्रतिशत {w:conj:d1} {crude} रुपये प्रति बैरल पर बंद हुआ, और सोना {p2} प्रतिशत {w:conj:d2} {gold} रुपये प्रति दस ग्राम पर।",
              "ta": "MCX-இல் நேற்றிரவு கச்சா எண்ணெய் {p1} சதவீதம் {w:conj:d1} பீப்பாய்க்கு {crude} ரூபாயில் நிறைவடைந்தது; தங்கம் {p2} சதவீதம் {w:conj:d2} பத்து கிராமுக்கு {gold} ரூபாயில் நிறைவடைந்தது.",
              "mr": "MCX वर काल रात्री कच्चे तेल {p1} टक्क्यांनी {w:conj:d1} प्रति बॅरल {crude} रुपयांवर बंद झाले, तर सोने {p2} टक्क्यांनी {w:conj:d2} प्रति दहा ग्रॅम {gold} रुपयांवर.",
              "gu": "MCX પર ગઈ રાત્રે ક્રૂડ ઓઇલ {p1} ટકા {w:conj:d1} બેરલ દીઠ {crude} રૂપિયા પર બંધ થયું, અને સોનું {p2} ટકા {w:conj:d2} દસ ગ્રામ દીઠ {gold} રૂપિયા પર."},
    # ---- pre-open
    "o_pre.move": {"en": "The pre-open is in. Priced on its constituent stocks, the Nifty is indicated near {lvl}, about {pct} percent {w:ind:d} than {dow}'s close.",
                 "hi": "प्री-ओपन के भाव आ गए हैं। इसके शेयरों के भाव के आधार पर निफ्टी {lvl} के आसपास संकेतित है, यानी {dow} के बंद भाव से करीब {pct} प्रतिशत {w:ind:d}।",
                 "ta": "ப்ரீ-ஓப்பன் விலைகள் வந்துவிட்டன. அதன் பங்குகளின் விலைகளின்படி நிஃப்டி சுமார் {lvl} அளவில் உள்ளது; இது {dow} முடிவை விட சுமார் {pct} சதவீதம் {w:ind:d}.",
                 "mr": "प्री-ओपनचे भाव आले आहेत. त्याच्या शेअर्सच्या भावांनुसार निफ्टी सुमारे {lvl} वर दिसत आहे, म्हणजे {dow} च्या बंद भावापेक्षा सुमारे {pct} टक्के {w:ind:d}.",
                 "gu": "પ્રી-ઓપનના ભાવ આવી ગયા છે. તેના શેરોના ભાવ મુજબ નિફ્ટી આશરે {lvl} પર દેખાય છે, એટલે કે {dow}ના બંધ ભાવથી આશરે {pct} ટકા {w:ind:d}."},
    "o_pre.flat": {"en": "The pre-open is in. Priced on its constituent stocks, the Nifty is indicated near {lvl}, close to {dow}'s close.",
                   "hi": "प्री-ओपन के भाव आ गए हैं। इसके शेयरों के भाव के आधार पर निफ्टी {lvl} के आसपास संकेतित है, यानी {dow} के बंद भाव के करीब।",
                   "ta": "ப்ரீ-ஓப்பன் விலைகள் வந்துவிட்டன. அதன் பங்குகளின் விலைகளின்படி நிஃப்டி சுமார் {lvl} அளவில் உள்ளது, {dow} முடிவுக்கு அருகில்.",
                   "mr": "प्री-ओपनचे भाव आले आहेत. त्याच्या शेअर्सच्या भावांनुसार निफ्टी सुमारे {lvl} वर दिसत आहे, म्हणजे {dow} च्या बंद भावाजवळ.",
                   "gu": "પ્રી-ઓપનના ભાવ આવી ગયા છે. તેના શેરોના ભાવ મુજબ નિફ્ટી આશરે {lvl} પર દેખાય છે, એટલે કે {dow}ના બંધ ભાવની નજીક."},
    "o_pre.wait": {"en": "The pre-open auction runs from nine to eight minutes past nine; its prices are added here as soon as they land.",
                   "hi": "प्री-ओपन नीलामी नौ बजे से नौ बजकर आठ मिनट तक चलती है; इसके भाव आते ही यहाँ जोड़े जाते हैं।",
                   "ta": "ப்ரீ-ஓப்பன் ஏலம் ஒன்பது மணி முதல் ஒன்பது மணி எட்டு நிமிடம் வரை நடக்கிறது; அதன் விலைகள் வந்தவுடன் இங்கே சேர்க்கப்படும்.",
                   "mr": "प्री-ओपन लिलाव नऊ ते नऊ वाजून आठ मिनिटांपर्यंत चालतो; त्याचे भाव येताच इथे जोडले जातात.",
                   "gu": "પ્રી-ઓપન હરાજી નવથી નવ વાગીને આઠ મિનિટ સુધી ચાલે છે; તેના ભાવ આવતાં જ અહીં ઉમેરાય છે."},
    "o_pre_breadth": {"en": "Across F and O stocks, {adv} are indicated higher and {dec} lower.",
                      "hi": "एफ़ एंड ओ शेयरों में {adv} ऊपर और {dec} नीचे संकेतित हैं।",
                      "ta": "எஃப் அண்ட் ஓ பங்குகளில் {adv} உயர்வாகவும் {dec} குறைவாகவும் உள்ளன.",
                      "mr": "एफ अँड ओ शेअर्सपैकी {adv} वर आणि {dec} खाली दिसत आहेत.",
                      "gu": "એફ એન્ડ ઓ શેરોમાં {adv} ઉપર અને {dec} નીચે દેખાય છે."},
    "o_gap_up": {"en": "Leading the gap-ups: {items}.", "hi": "सबसे ज़्यादा ऊपर खुलने के संकेत: {items}।",
                 "ta": "அதிக உயர்வுடன் தொடங்கும் குறிப்புகள்: {items}.", "mr": "सर्वाधिक वर उघडण्याचे संकेत: {items}.",
                 "gu": "સૌથી વધુ ઉપર ખૂલવાના સંકેત: {items}."},
    "o_gap_dn": {"en": "And the biggest gap-downs: {items}.", "hi": "और सबसे ज़्यादा नीचे खुलने के संकेत: {items}।",
                 "ta": "அதிக சரிவுடன் தொடங்கும் குறிப்புகள்: {items}.", "mr": "आणि सर्वाधिक खाली उघडण्याचे संकेत: {items}.",
                 "gu": "અને સૌથી વધુ નીચે ખૂલવાના સંકેત: {items}."},
    "gap_up_item": {"en": "{name}, up {pct} percent", "hi": "{name} {pct} प्रतिशत ऊपर", "ta": "{name} {pct} சதவீதம் உயர்வு",
                    "mr": "{name} {pct} टक्के वर", "gu": "{name} {pct} ટકા ઉપર"},
    "gap_dn_item": {"en": "{name}, down {pct} percent", "hi": "{name} {pct} प्रतिशत नीचे", "ta": "{name} {pct} சதவீதம் சரிவு",
                    "mr": "{name} {pct} टक्के खाली", "gu": "{name} {pct} ટકા નીચે"},
    "o_pre_after": {"en": "Reacting to results filed after {dow}'s close: {items}.", "hi": "{dow} के बंद होने के बाद आए नतीजों पर प्रतिक्रिया: {items}।",
                    "ta": "{dow} முடிவுக்குப் பின் வந்த முடிவுகளுக்கான எதிர்வினை: {items}.", "mr": "{dow} च्या बंदनंतर आलेल्या निकालांवर प्रतिक्रिया: {items}.",
                    "gu": "{dow}ના બંધ પછી આવેલા પરિણામો પર પ્રતિક્રિયા: {items}."},
    "o_pre_ideas": {"en": "On the desk's AI list: {items}.", "hi": "डेस्क की AI लिस्ट में: {items}।", "ta": "டெஸ்கின் AI பட்டியலில்: {items}.",
                    "mr": "डेस्कच्या AI यादीत: {items}.", "gu": "ડેસ્કની AI યાદીમાં: {items}."},
    "o_pre_note": {"en": "Pre-open prices can shift once normal trading starts at {time}.",
                   "hi": "सामान्य कारोबार {time} शुरू होने के बाद प्री-ओपन के भाव बदल सकते हैं।",
                   "ta": "{time} வழக்கமான வர்த்தகம் தொடங்கியதும் ப்ரீ-ஓப்பன் விலைகள் மாறலாம்.",
                   "mr": "{time} नियमित व्यवहार सुरू झाल्यावर प्री-ओपनचे भाव बदलू शकतात.",
                   "gu": "{time} સામાન્ય કારોબાર શરૂ થયા પછી પ્રી-ઓપનના ભાવ બદલાઈ શકે છે."},
    # ---- ranges and levels
    "o_vix": {"en": "Now, the range. India VIX closed at {vix}. That prices a typical one-day move of about {pts} points for the Nifty, either way: {lo} to {hi} from {dow}'s close.",
              "hi": "अब, रेंज। इंडिया VIX {vix} पर बंद हुआ। इसके हिसाब से निफ्टी में एक दिन की सामान्य चाल दोनों तरफ़ करीब {pts} अंकों की है: {dow} के बंद भाव से {lo} से {hi} तक।",
              "ta": "இப்போது, வரம்பு. இந்தியா VIX {vix} இல் நிறைவடைந்தது. இதன்படி நிஃப்டியில் ஒரு நாளின் வழக்கமான நகர்வு இரு பக்கமும் சுமார் {pts} புள்ளிகள்: {dow} முடிவிலிருந்து {lo} முதல் {hi} வரை.",
              "mr": "आता, रेंज. इंडिया VIX {vix} वर बंद झाला. त्यानुसार निफ्टीत एका दिवसाची सर्वसाधारण हालचाल दोन्ही बाजूंना सुमारे {pts} अंकांची आहे: {dow} च्या बंद भावापासून {lo} ते {hi}.",
              "gu": "હવે, રેન્જ. ઇન્ડિયા VIX {vix} પર બંધ થયો. તે મુજબ નિફ્ટીમાં એક દિવસની સામાન્ય ચાલ બંને તરફ આશરે {pts} પોઇન્ટની છે: {dow}ના બંધ ભાવથી {lo} થી {hi}."},
    "o_oi": {"en": "In the nearest Nifty options expiry, the largest put open interest sits at {sup}, and the largest call open interest at {res}. Traders often read these as support and resistance.",
             "hi": "निफ्टी की सबसे नज़दीकी एक्सपायरी के ऑप्शंस में सबसे ज़्यादा पुट ओपन इंटरेस्ट {sup} पर है, और सबसे ज़्यादा कॉल ओपन इंटरेस्ट {res} पर। ट्रेडर अक्सर इन्हें सपोर्ट और रेज़िस्टेंस मानते हैं।",
             "ta": "நிஃப்டியின் அருகிலுள்ள காலாவதி ஆப்ஷன்களில் அதிகபட்ச புட் ஓப்பன் இன்ட்ரஸ்ட் {sup} இல் உள்ளது, அதிகபட்ச கால் ஓப்பன் இன்ட்ரஸ்ட் {res} இல் உள்ளது. வர்த்தகர்கள் இவற்றை பெரும்பாலும் சப்போர்ட் மற்றும் ரெசிஸ்டன்ஸ் ஆகப் பார்க்கிறார்கள்.",
             "mr": "निफ्टीच्या सर्वात जवळच्या एक्स्पायरीच्या ऑप्शन्समध्ये सर्वाधिक पुट ओपन इंटरेस्ट {sup} वर आहे, आणि सर्वाधिक कॉल ओपन इंटरेस्ट {res} वर. ट्रेडर्स अनेकदा यांना सपोर्ट आणि रेझिस्टन्स मानतात.",
             "gu": "નિફ્ટીની સૌથી નજીકની એક્સપાયરીના ઓપ્શન્સમાં સૌથી વધુ પુટ ઓપન ઇન્ટરેસ્ટ {sup} પર છે, અને સૌથી વધુ કોલ ઓપન ઇન્ટરેસ્ટ {res} પર. ટ્રેડર્સ ઘણીવાર તેને સપોર્ટ અને રેઝિસ્ટન્સ માને છે."},
    "o_pcr": {"en": "The put-call ratio is {pcr}, and max pain, where option buyers as a group would lose the most at expiry, is {mp}.",
              "hi": "पुट-कॉल रेशियो {pcr} है, और मैक्स पेन, यानी वह स्तर जहाँ एक्सपायरी पर ऑप्शन ख़रीदारों को कुल मिलाकर सबसे ज़्यादा नुकसान होगा, {mp} पर है।",
              "ta": "புட்-கால் விகிதம் {pcr}; மேக்ஸ் பெயின், அதாவது காலாவதியில் ஆப்ஷன் வாங்குபவர்கள் மொத்தமாக அதிகம் இழக்கும் நிலை, {mp}.",
              "mr": "पुट-कॉल रेशो {pcr} आहे, आणि मॅक्स पेन, म्हणजे एक्स्पायरीला ऑप्शन खरेदीदारांचे एकूण सर्वाधिक नुकसान होईल ती पातळी, {mp} वर आहे.",
              "gu": "પુટ-કોલ રેશિયો {pcr} છે, અને મેક્સ પેઇન, એટલે કે એક્સપાયરી પર ઓપ્શન ખરીદનારાઓને કુલ મળીને સૌથી વધુ નુકસાન થાય તે સ્તર, {mp} પર છે."},
    "o_straddle": {"en": "It's expiry day. The {atm} straddle closed at {strad} points, about {pct} percent of the index: the move the options market is pricing for today.",
                   "hi": "आज एक्सपायरी का दिन है। {atm} का स्ट्रैडल {strad} अंकों पर बंद हुआ, यानी इंडेक्स का करीब {pct} प्रतिशत: आज के लिए ऑप्शंस बाज़ार इतनी चाल का भाव लगा रहा है।",
                   "ta": "இன்று காலாவதி நாள். {atm} ஸ்ட்ராடில் {strad} புள்ளிகளில் நிறைவடைந்தது, குறியீட்டின் சுமார் {pct} சதவீதம்: இன்றைக்கு ஆப்ஷன் சந்தை கணக்கிடும் நகர்வு இது.",
                   "mr": "आज एक्स्पायरीचा दिवस आहे. {atm} चा स्ट्रॅडल {strad} अंकांवर बंद झाला, म्हणजे निर्देशांकाच्या सुमारे {pct} टक्के: आजसाठी ऑप्शन्स बाजार इतक्या हालचालीचा भाव लावत आहे.",
                   "gu": "આજે એક્સપાયરીનો દિવસ છે. {atm}નો સ્ટ્રેડલ {strad} પોઇન્ટ પર બંધ થયો, એટલે કે ઇન્ડેક્સના આશરે {pct} ટકા: આજ માટે ઓપ્શન્સ બજાર આટલી ચાલનો ભાવ આંકે છે."},
    "o_implied": {"en": "For today's results, options price these moves to the {expiry} expiry: {items}.",
                  "hi": "आज नतीजे देने वाली कंपनियों के लिए ऑप्शंस {expiry} की एक्सपायरी तक इतनी चाल का भाव लगा रहे हैं: {items}।",
                  "ta": "இன்று முடிவுகள் வெளியிடும் நிறுவனங்களுக்கு, {expiry} காலாவதி வரை ஆப்ஷன்கள் கணக்கிடும் நகர்வு: {items}.",
                  "mr": "आज निकाल जाहीर करणाऱ्या कंपन्यांसाठी ऑप्शन्स {expiry} च्या एक्स्पायरीपर्यंत इतक्या हालचालीचा भाव लावत आहेत: {items}.",
                  "gu": "આજે પરિણામ આપતી કંપનીઓ માટે ઓપ્શન્સ {expiry}ની એક્સપાયરી સુધી આટલી ચાલનો ભાવ આંકે છે: {items}."},
    "imp_item": {"en": "{name}, about {pct} percent either way", "hi": "{name} दोनों तरफ़ करीब {pct} प्रतिशत", "ta": "{name} இரு பக்கமும் சுமார் {pct} சதவீதம்",
                 "mr": "{name} दोन्ही बाजूंना सुमारे {pct} टक्के", "gu": "{name} બંને તરફ આશરે {pct} ટકા"},
    "o_levels_note": {"en": "These are ranges the options market is pricing, not forecasts.",
                      "hi": "ये ऑप्शंस बाज़ार की आंकी गई रेंज हैं, पूर्वानुमान नहीं।",
                      "ta": "இவை ஆப்ஷன் சந்தை கணக்கிடும் வரம்புகள், முன்னறிவிப்புகள் அல்ல.",
                      "mr": "या ऑप्शन्स बाजाराने आखलेल्या रेंज आहेत, अंदाज नाहीत.",
                      "gu": "આ ઓપ્શન્સ બજારે આંકેલી રેન્જ છે, આગાહી નથી."},
    # ---- AI lists (morning wording; idea.*, fno, fno_list and ai_close are shared)
    "o_ai_intro": {"en": "Now, the desk's AI scanner lists for today. These are ideas for review, not recommendations, and the desk's own scorecard shows no measurable ranking skill yet.",
                   "hi": "अब, आज के लिए डेस्क के AI स्कैनर की लिस्ट। ये समीक्षा के लिए आइडिया हैं, सिफ़ारिशें नहीं, और डेस्क के अपने स्कोरकार्ड में अभी रैंकिंग की कोई मापने योग्य क्षमता नहीं दिखी है।",
                   "ta": "இப்போது, இன்றைக்கான டெஸ்கின் AI ஸ்கேனர் பட்டியல்கள். இவை பரிசீலனைக்கான யோசனைகள் மட்டுமே, பரிந்துரைகள் அல்ல; டெஸ்கின் சொந்த மதிப்பீட்டில் இன்னும் அளவிடக்கூடிய தரவரிசைத் திறன் தெரியவில்லை.",
                   "mr": "आता, आजसाठी डेस्कच्या AI स्कॅनरच्या याद्या. या आढाव्यासाठीच्या कल्पना आहेत, शिफारसी नाहीत, आणि डेस्कच्या स्वतःच्या स्कोअरकार्डमध्ये अजून मोजता येईल अशी क्रमवारी क्षमता दिसलेली नाही.",
                   "gu": "હવે, આજ માટે ડેસ્કની AI સ્કેનર યાદીઓ. આ સમીક્ષા માટેના આઇડિયા છે, ભલામણો નહીં, અને ડેસ્કના પોતાના સ્કોરકાર્ડમાં હજુ માપી શકાય તેવી રેન્કિંગ ક્ષમતા દેખાઈ નથી."},
    # ---- today
    "o_macro": {"en": "On the calendar today: {items}.", "hi": "आज के कैलेंडर में: {items}।", "ta": "இன்றைய அட்டவணையில்: {items}.",
                "mr": "आजच्या कॅलेंडरमध्ये: {items}.", "gu": "આજના કેલેન્ડરમાં: {items}."},
    "o_due": {"en": "Results due today from the F and O list: {due}.", "hi": "एफ़ एंड ओ लिस्ट से आज इनके नतीजे: {due}।",
              "ta": "எஃப் அண்ட் ஓ பட்டியலில் இன்று முடிவுகள் வெளியிடுபவை: {due}.", "mr": "एफ अँड ओ यादीतील आज निकाल जाहीर करणाऱ्या कंपन्या: {due}.",
              "gu": "એફ એન્ડ ઓ યાદીમાંથી આજે આ કંપનીઓના પરિણામ: {due}."},
    "o_signoff.0": {"en": "That's the Opening Bell from the Nivesh Desk. Trading starts at {time}."},
    "o_signoff.1": {"en": "And that's the Opening Bell, from the Nivesh Desk. Trading starts at {time}."},
    "o_signoff": {"hi": "निवेश डेस्क से ओपनिंग बेल में बस इतना ही। कारोबार {time} शुरू होगा।",
                  "ta": "நிவேஷ் டெஸ்கின் ஓப்பனிங் பெல் இத்துடன் நிறைவடைகிறது. வர்த்தகம் {time} தொடங்கும்.",
                  "mr": "निवेश डेस्कवरून ओपनिंग बेल इथेच संपते. व्यवहार {time} सुरू होतील.",
                  "gu": "નિવેશ ડેસ્ક પરથી ઓપનિંગ બેલ અહીં પૂરું થાય છે. કારોબાર {time} શરૂ થશે."},
    "o_disclaimer": {"en": "Market information and education, not investment advice. Have a good session.",
                     "hi": "यह बाज़ार की जानकारी और शिक्षा है, निवेश सलाह नहीं। आपका दिन शुभ हो।",
                     "ta": "இது சந்தைத் தகவலும் கல்வியும் மட்டுமே, முதலீட்டு ஆலோசனை அல்ல. இனிய வர்த்தக நாள் அமையட்டும்.",
                     "mr": "ही बाजाराची माहिती आणि शिक्षण आहे, गुंतवणूक सल्ला नाही. आपला दिवस शुभ जावो.",
                     "gu": "આ બજારની માહિતી અને શિક્ષણ છે, રોકાણ સલાહ નથી. આપનો દિવસ શુભ રહે."},
}

clash = set(T) & set(i18n.T)
assert not clash, f"opening template keys clash with the evening's: {sorted(clash)}"
i18n.T.update(T)
for _lang, tables in WORDS.items():
    for _name, table in tables.items():
        i18n.WORDS[_lang].setdefault(_name, table)
for _tag, v in SECTION_TITLES.items():
    i18n.SECTION_TITLES.setdefault(_tag, v)
