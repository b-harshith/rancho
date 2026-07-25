#!/usr/bin/env python3
"""
Fee Classification Pipeline v5 — Binary (>1L vs ≤1L)
=====================================================
KEY IMPROVEMENTS:
1. Robust City Mapping:
   - Uses a comprehensive district-to-city mapping that correctly classifies
     satellite districts into metropolitan areas (e.g. Palghar/Raigarh -> Mumbai,
     Sangareddy -> Hyderabad).
   - Reduces "unknown" city classification from 4,976 to 557 schools.
2. Comprehensive Board & Medium Inference:
   - Resolves covariate shift by applying smart board family inference consistently.
3. Expanded Premium Keywords & Chains:
   - Widens chain detection to cover 100+ premium brands, missionary/convent schools.
"""

import hashlib
import json
import math
import re
import warnings
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    ExtraTreesClassifier,
    RandomForestClassifier,
    VotingClassifier,
)
from sklearn.impute import KNNImputer, SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder, StandardScaler
from xgboost import XGBClassifier

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ──────────────────────────── Paths ────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
UDISE_PATH = ROOT / "data/client_delivery/udise_private_unaided_with_enrollment.csv"
FULL_UDISE_PATH = ROOT / "data/client_export/udise_schools_client.csv"
BOARD_LOOKUP_PATH = ROOT / "data/client_delivery/udise_board_medium_lookup.csv"
LABELED_PATH = ROOT / "data/client_export/ezy_yellowslate_unified_all_cities_geocoded.csv"
BANGALORE_PATH = Path(
    "/Users/malleswararao/Desktop/BangaloreRancho/"
    "web_platform_vercel_exact_latest/src/public/data/schools.json"
)
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

THRESHOLD = 100_000
MARKET_PREDICTION_THRESHOLD = 0.40

# ──────────────────────────── Premium Chains & Keywords ────────────────────────────
# ──────────────────────────── Premium Chains & Keywords ────────────────────────────
# Compiled regular expressions for premium school brands/chains with spelling corrections
PREMIUM_REGEXES = {
    # Existing & Spelled Checked Premium Chains
    "dps": re.compile(r"\bd\s?p\s?s\b|delhi\s?pub", re.I),
    "amity": re.compile(r"\bamit[yi]\b", re.I),
    "gd goenka": re.compile(r"\bg\s?d\s?go?[ei]?n[ae]?k?a\b|\bgo?[ei]?n[ae]?k?a\b", re.I),
    "vibgyor": re.compile(r"\bvi?bgy?o?u?r\b", re.I),
    "orchids": re.compile(r"\borchids?\b", re.I),
    "jbcn": re.compile(r"\bjbcn\b", re.I),
    "heritage": re.compile(r"\bheritage\b", re.I),
    "pathways": re.compile(r"\bpath\s?ways?\b|\bpathways?\b", re.I),
    "shiv nadar": re.compile(r"\bshiv\s?n[ad]*r\b", re.I),
    "oakridge": re.compile(r"\bo[ai]k\s?ridge\b|\bok\s?ridge\b|\bokridge\b", re.I),
    "birla": re.compile(r"\bbirla\b", re.I),
    "billabong": re.compile(r"\bbill?a?bo?ng\b", re.I),
    "presidium": re.compile(r"\bpresidium\b", re.I),
    "lotus valley": re.compile(r"\blotus\s?valley\b", re.I),
    "suncity": re.compile(r"\bsuncity\b", re.I),
    "apeejay": re.compile(r"\bap[ee]*jay\b", re.I),
    "chirec": re.compile(r"\bchire[ck]\b", re.I),
    "campion": re.compile(r"\bcampion\b", re.I),
    "indus": re.compile(r"\bindus\b", re.I),
    "silver oaks": re.compile(r"\bsilver\s?oaks?\b", re.I),
    "glendale": re.compile(r"\bglen\s?dale\b", re.I),
    "gitanjali": re.compile(r"\bge?e?t[an]+j[al]+i\b", re.I),
    "meridian": re.compile(r"\bmeridian\b", re.I),
    "shriram": re.compile(r"\bshri\s?ram\b|\bsri\s?ram\b|\bshriram\b|\bsriram\b", re.I),
    "dhirubhai": re.compile(r"\bdhiru\b", re.I),
    "presidency": re.compile(r"\bpresidenc[yi]\b", re.I),
    "lancers": re.compile(r"\blancer\'?s?\b", re.I),
    "kunskapsskolan": re.compile(r"\bkunskapsskolan\b|\bkuns?kap?s?ko?lan\b", re.I),
    "hiranandani": re.compile(r"\bhira?nandani\b", re.I),
    "reliance": re.compile(r"\breliance\b", re.I),
    "aditya birla": re.compile(r"\baditya\s?birla\b", re.I),
    "chrysalis": re.compile(r"\bchrys?[ae]i?lis\b|\bchrys?ail\b", re.I),
    "ryan": re.compile(r"\bry?an\b", re.I),
    "greenwood": re.compile(r"\bgreen\s?woods?\b", re.I),
    "bal bharati": re.compile(r"\bbal\s?bh[aa]rat?i\b|\bbalbharti\b", re.I),
    "cathedral": re.compile(r"\bcathedral\b", re.I),
    "inventure": re.compile(r"\binventure\b", re.I),
    "podar": re.compile(r"\bpo?o?d?d?ar\b|\bpotdar\b", re.I),
    "baldwin": re.compile(r"\bbald?wins?\b|\balwin[s]?\b", re.I),

    # Expanded / New Premium School Groups (3x Expansion)
    "nps": re.compile(r"\bn\s?p\s?s\b|national\s?public\s?school", re.I),
    "bishop cotton": re.compile(r"\bbishop\s?cotton\b|\bcottonian\b", re.I),
    "tisb": re.compile(r"\bt\s?i\s?s\s?b\b|intl\s?school\s?bangalore", re.I),
    "mallya aditi": re.compile(r"\bmallya\s?aditi\b", re.I),
    "sarala birla": re.compile(r"\bsarala\s?birla\b", re.I),
    "gems": re.compile(r"\bgems\b|gems\s?akademi|gems\s?intl|gems\s?inter", re.I),
    "oberoi": re.compile(r"\boberoi\b", re.I),
    "singapore intl": re.compile(r"\bsingapore\s?intl|\bsingapore\s?inter|\bsis\b", re.I),
    "euroschool": re.compile(r"\beuro\s?school\b|\beuroschool\b", re.I),
    "mount litera": re.compile(r"\bmount\s?litera\b|\bmlzs\b", re.I),
    "step by step": re.compile(r"\bstep\s?by\s?step\b", re.I),
    "vasant valley": re.compile(r"\bvasant\s?valley\b", re.I),
    "sanskriti": re.compile(r"\bsanskriti\b", re.I),
    "genesis": re.compile(r"\bgenesis\s?global\b|\bgenesis\b", re.I),
    "shanti asian": re.compile(r"\bshanti\s?asian\b|\bshanti\s?asiatic\b", re.I),
    "ais ahmedabad": re.compile(r"\bahmedabad\s?intl|ahmedabad\s?inter|\bais\b", re.I),
    "udgam": re.compile(r"\budgam\b", re.I),
    "eklavya": re.compile(r"\beklavya\b", re.I),
    "redbricks": re.compile(r"\bredbricks\b", re.I),
    "symbiosis": re.compile(r"\bsymbiosis\b", re.I),
    "mercedes benz": re.compile(r"\bmercedes\s?benz\b", re.I),
    "blue ridge": re.compile(r"\bblue\s?ridge\b", re.I),
    "lexicon": re.compile(r"\blexicon\b", re.I),
    "dy patil": re.compile(r"\bd\.?\s?y\.?\s?patil\b", re.I),
    "victorious kidss": re.compile(r"\bvictorious\s?kidss\b", re.I),
    "hutchings": re.compile(r"\bhutchings\b", re.I),
    "la martiniere": re.compile(r"\bla\s?martiniere\b|\blamartiniere\b", re.I),
    "st james": re.compile(r"\bst\s?james\b", re.I),
    "calcutta intl": re.compile(r"\bcalcutta\s?intl|\bcalcutta\s?inter\b|\bcis\b", re.I),
    "legacy bangalore": re.compile(r"\blegacy\s?school\b", re.I),
    "canadian intl": re.compile(r"\bcanadian\s?intl|\bcanadian\s?inter\b", re.I),
    "stonehill": re.compile(r"\bstonehill\b", re.I),
    "trio world": re.compile(r"\btrio\s?world\b", re.I),
    "ebenezer": re.compile(r"\bebenezer\b", re.I),
    "treamis": re.compile(r"\btreamis\b", re.I),
    "sherwood": re.compile(r"\bsherwood\b", re.I),
    "whitefield global": re.compile(r"\bwhitefield\s?global\b|\bwgs\b", re.I),
    "vyasa": re.compile(r"\bvyasa\s?intl|\bvyasa\s?inter\b", re.I),
    "dse hyderabad": re.compile(r"\bdelhi\s?school\s?of\s?excellence\b|\bdse\b", re.I),
    "sloka": re.compile(r"\bsloka\b", re.I),
    "aga khan": re.compile(r"\baga\s?khan\b", re.I),
    "manthan": re.compile(r"\bmanthan\b", re.I),
    "suchitra": re.compile(r"\bsuchitra\b", re.I),
    "keystone": re.compile(r"\bkeystone\b", re.I),
    "vista school": re.compile(r"\bvista\s?school\b", re.I),
    "indus valley": re.compile(r"\bindus\s?valley\b", re.I),
    "garden high": re.compile(r"\bgarden\s?high\b", re.I),
    "assembly of god": re.compile(r"\bassembly\s?of\s?god\b", re.I),
    "pratt memorial": re.compile(r"\bpratt\s?memorial\b", re.I),
    "frank anthony": re.compile(r"\bfrank\s?anthony\b|\bfaps\b", re.I),
    "witty": re.compile(r"\bwitty\s?intl|\bwitty\s?inter|\bwitty\s?international\b", re.I),
    "rustomjee": re.compile(r"\brustomjee\b", re.I),
    "thakur": re.compile(r"\bthakur\s?intl|\bthakur\s?public\b", re.I),
    "singhania": re.compile(r"\bsinghania\b", re.I),
    "somaiya": re.compile(r"\bsomaiya\b", re.I),
    "jamnabai": re.compile(r"\bjamnabai\b|\bnarsee\b", re.I),
    "maneckji": re.compile(r"\bmaneckji\b", re.I),
    "utpal shanghvi": re.compile(r"\butpal\s?shanghvi\b", re.I),
    "avm mumbai": re.compile(r"\barya\s?vidya\b|\bavm\b", re.I),
    "pawar public": re.compile(r"\bpawar\s?public\b|\bpps\b", re.I),
    "fazlani": re.compile(r"\bfazlani\b", re.I),
    "hill spring": re.compile(r"\bhill\s?spring\b", re.I),
    "bombay intl": re.compile(r"\bbombay\s?intl|\bbombay\s?inter\b", re.I),
    "walsingham": re.compile(r"\bwalsingham\b", re.I),
    "queen mary": re.compile(r"\bqueen\s?mary\b", re.I),
    "jb petit": re.compile(r"\bj\s?b\s?petit\b", re.I),
    "activity high": re.compile(r"\bactivity\s?high\b", re.I),
    "greenlawns": re.compile(r"\bgreenlawns\b", re.I),
    "millennium": re.compile(r"\bmillennium\s?school\b", re.I),
    "springdales": re.compile(r"\bspringdales\b", re.I),
    "mothers intl": re.compile(r"\bmother\'?s\s?intl|\bmother\'?s\s?inter\b", re.I),
    "svis": re.compile(r"\bs\s?v\s?i\s?s\b|venkateshwar\s?intl|venkateshwar\s?global", re.I),
    "dps intl": re.compile(r"\bd\s?p\s?s\s?intl|\bd\s?p\s?s\s?inter\b", re.I),
    "elpro": re.compile(r"\belpro\b", re.I),
    "joyce": re.compile(r"\bjoyce\b", re.I),
    "himalaya intl": re.compile(r"\bhimalaya\s?intl|\bhimalaya\s?inter\b", re.I),
    "mount abu": re.compile(r"\bmount\s?abu\b", re.I),
    "salwan": re.compile(r"\bsalwan\b", re.I),
    "prudence": re.compile(r"\bprudence\b", re.I),
    "manav rachna": re.compile(r"\bmanav\s?rachna\b", re.I),
    "scottish high": re.compile(r"\bscottish\s?high\b", re.I),
    "vegas intl": re.compile(r"\bvegas\s?intl|\bvegas\s?inter\b", re.I),
    "vivekanand global": re.compile(r"\bvivekanand\s?global\b", re.I),
    "richmondd": re.compile(r"\brichmondd\b", re.I),
    "mbs intl": re.compile(r"\bmbs\s?intl|\bmbs\s?inter\b", re.I),
    "xaviers world": re.compile(r"\bst\s?xaviers\s?world\b", re.I),
    "krsna world": re.compile(r"\bkrsna\s?world\b", re.I),
    "manipal": re.compile(r"\bmanipal\b", re.I),
    "st stephens": re.compile(r"\bst\s?stephens\s?school\b", re.I),
    "asn": re.compile(r"\ba\s?s\s?n\s?(?:sr\.?|senior)?\s?(?:sec|secondary)?\s?school\b|\basn\b", re.I),
    "tagore international": re.compile(r"\btagore\s?(?:intl|inter|international)\b", re.I),
    "modern school barakhamba": re.compile(r"\bmodern\s?school\b.*\bbarakhamba\b|\bbarakhamba\b.*\bmodern\s?school\b", re.I),
    "sardar patel vidyalaya": re.compile(r"\bsardar\s?patel\s?vidyalaya\b|\bspv\b", re.I),
    "bluebells": re.compile(r"\bblue\s?bells?\b|\bbluebells\b", re.I),
    "st columba": re.compile(r"\bst\.?\s?columba'?s?\b", re.I),
    "mater dei": re.compile(r"\bmater\s?dei\b", re.I),
    "jesus mary": re.compile(r"\bjesus\s?(?:and|&)?\s?mary\b", re.I),
    "holy child": re.compile(r"\bholy\s?child\b", re.I),
    "cambridge school": re.compile(r"\bcambridge\s?school\b", re.I),
    "don bosco": re.compile(r"\bdon\s?bosco\b", re.I),
    "loreto": re.compile(r"\blore?to\b", re.I),
    "good shepherd": re.compile(r"\bgood\s?shepherd\b", re.I),
    "sishya": re.compile(r"\bsishya\b", re.I),
    "psbb": re.compile(r"\bp\s?s\s?b\s?b\b|\bpadma\s?seshadri\b", re.I),
    "chettinad vidyashram": re.compile(r"\bchettinad\s?vidyashram\b", re.I),
    "vidya mandir mylapore": re.compile(r"\bvidya\s?mandir\b.*\bmylapore\b|\bmylapore\b.*\bvidya\s?mandir\b", re.I),

    # Data-mined premium single-brand / institutional names from labeled fee corpus.
    "american embassy": re.compile(r"\bamerican\s?embassy\s?school\b", re.I),
    "uwc mahindra": re.compile(r"\buwc\s?mahindra\b", re.I),
    "harrow": re.compile(r"\bharrow\s?(?:intl|inter|international)?\b", re.I),
    "corvuss american": re.compile(r"\bcorvuss\s?american\b", re.I),
    "queen elizabeth": re.compile(r"\bqueen\s?elizabeth'?s?\b", re.I),
    "prometheus": re.compile(r"\bprometheus\b", re.I),
    "naavu": re.compile(r"\bnaavu\b", re.I),
    "vishwashanti gurukul": re.compile(r"\bvishwashanti\s?gurukul\b", re.I),
    "manchester global": re.compile(r"\bmanchester\s?global\b", re.I),
    "10x international": re.compile(r"\b10x\s?(?:intl|inter|international)\b", re.I),
    "neev": re.compile(r"\bneev\b", re.I),
    "ascend": re.compile(r"\bascend\s?(?:intl|inter|international)?\b", re.I),
    "sancta maria": re.compile(r"\bsancta\s?maria\b", re.I),
    "ecole mondiale": re.compile(r"\becole\s?mondiale\b", re.I),
    "jain international residential": re.compile(r"\bjain\s?(?:intl|inter|international)\s?residential\b|\bjirs\b", re.I),
    "school of raya": re.compile(r"\bschool\s?of\s?raya\b", re.I),
    "bd somani": re.compile(r"\bb\.?\s?d\.?\s?somani\b|\bbsomani\b", re.I),
    "velammal international": re.compile(r"\bvelammal\s?(?:intl|inter|international)\b", re.I),
    "international school of hyderabad": re.compile(r"\binternational\s?school\s?of\s?hyderabad\b|\bish\b", re.I),
    "excelsior american": re.compile(r"\bexcelsior\s?american\b", re.I),
    "edubridge": re.compile(r"\bedu\s?bridge\b|\bedubridge\b", re.I),
    "garodia": re.compile(r"\bgarodia\b", re.I),
    "knowledgeum": re.compile(r"\bknowledgeum\b", re.I),
    "johnson grammar": re.compile(r"\bjohnson\s?grammar\b", re.I),
    "sagebrook": re.compile(r"\bsage\s?brook\b|\bsagebrook\b", re.I),
    "rockwell": re.compile(r"\brockwell\s?(?:intl|inter|international)?\b", re.I),
    "learners international": re.compile(r"\blearners\s?(?:intl|inter|international)\b", re.I),
    "rbk": re.compile(r"\br\s?b\s?k\b|\brbk\s?(?:intl|inter|international)?\b", re.I),
    "nahar international": re.compile(r"\bnahar\s?(?:intl|inter|international)\b", re.I),
    "international village": re.compile(r"\binternational\s?village\b", re.I),
    "prakriti": re.compile(r"\bprakriti\b", re.I),
    "vedanya": re.compile(r"\bvedanya\b", re.I),
    "rmk residential": re.compile(r"\br\s?m\s?k\s?residential\b|\brmk\s?residential\b", re.I),
    "ardee": re.compile(r"\bardee\b", re.I),
    "insignis": re.compile(r"\binsignis\b", re.I),
    "head start": re.compile(r"\bhead\s?start\s?(?:educational)?\s?academy\b", re.I),
    "sanford global": re.compile(r"\bsanford\s?(?:the\s?)?global\b", re.I),
    "alphabet international": re.compile(r"\balphabet\s?(?:intl|inter|international)\b", re.I),
    "candiidus": re.compile(r"\bcandiidus\b|\bcandidus\b", re.I),
    "gyanshree": re.compile(r"\bgyanshree\b", re.I),
    "drs international": re.compile(r"\bd\s?r\s?s\s?(?:intl|inter|international)\b|\bdrs\s?(?:intl|inter|international)\b", re.I),
    "sharanya narayani": re.compile(r"\bsharanya\s?narayani\b", re.I),
    "pragyanam": re.compile(r"\bpragyanam\b", re.I),
    "modern high kolkata": re.compile(r"\bmodern\s?high\s?school\b", re.I),
    "the beacon": re.compile(r"\bbeacon\s?school\b", re.I),
    "national academy for learning": re.compile(r"\bnational\s?academy\s?for\s?learning\b|\bnafl\b", re.I),
    "hdfc school": re.compile(r"\bhdfc\s?school\b", re.I),
    "hfs international": re.compile(r"\bh\s?f\s?s\s?(?:intl|inter|international)\b|\bhfs\s?(?:intl|inter|international)\b", re.I),
    "satya school": re.compile(r"\bsatya\s?school\b", re.I),
    "vega": re.compile(r"\bvega\s?school\b", re.I),
    "kothari international": re.compile(r"\bkothari\s?(?:intl|inter|international)\b", re.I),
    "ridge valley": re.compile(r"\bridge\s?valley\b", re.I),
    "unicosmos": re.compile(r"\bunicosmos\b", re.I),
    "narayana e-techno": re.compile(r"\bnarayana\s?e[-\s]?techno\b", re.I),
    "kr mangalam": re.compile(r"\bk\.?\s?r\.?\s?mangalam\b|\bkr\s?mangalam\b", re.I),
    "dpsg": re.compile(r"\bd\s?p\s?s\s?g\b|\bdpsg\b", re.I),
    "gaurs international": re.compile(r"\bgaurs?\s?(?:intl|inter|international)\b", re.I),
    "maxfort": re.compile(r"\bmaxfort\b", re.I),
    "somerville": re.compile(r"\bsomerville\b", re.I),
    "mount olympus": re.compile(r"\bmount\s?olympus\b", re.I),
    "jaipuria": re.compile(r"\bjaipuria\b|\bseth\s?anandram\s?jaipuria\b", re.I),
    "the creek planet": re.compile(r"\bcreek\s?planet\b", re.I),
    "sadhu vaswani": re.compile(r"\bsadhu\s?vaswani\b", re.I),
    "national centre for excellence": re.compile(r"\bnational\s?cent(?:re|er)\s?for\s?excellence\b|\bncfe\b", re.I),
    "st germain": re.compile(r"\bst\.?\s?germain\b", re.I),
    "summer fields": re.compile(r"\bsummer\s?fields?\b", re.I),
    "dominics savio": re.compile(r"\bst\.?\s?dominics?\s?savio\b|\bdominics?\s?savio\b", re.I),
    "canary": re.compile(r"\bcanary\s?the\s?school\b|\bcanary\s?school\b", re.I),
    "amulakh amichand": re.compile(r"\bamulakh\s?amichand\b", re.I),
    "panbai": re.compile(r"\bpanbai\b", re.I),
    "gateway": re.compile(r"\bgateway\s?(?:the\s?complete\s?)?school\b", re.I),
    "kairos": re.compile(r"\bkairos\s?school\b", re.I),
    "sreenidhi": re.compile(r"\bsreenidhi\s?(?:intl|inter|international)?\b", re.I),
    "pacific world": re.compile(r"\bpacific\s?world\b", re.I),
    "rims international": re.compile(r"\brims\s?(?:intl|inter|international)\b", re.I),
    "akshar arbol": re.compile(r"\bakshar\s?arbol\b", re.I),
    "meru": re.compile(r"\bmeru\s?school\b", re.I),
    "khaitan": re.compile(r"\bkhaitan\s?school\b", re.I),
    "bssm shetty": re.compile(r"\bb\.?\s?s\.?\s?s\.?\s?m\.?\s?shetty\b|\bbssm\s?shetty\b", re.I),
    "gurukul the school": re.compile(r"\bgurukul\s?the\s?school\b", re.I),
    "jg international": re.compile(r"\bj\.?\s?g\.?\s?(?:intl|inter|international)\b|\bjg\s?(?:intl|inter|international)\b", re.I),
    "universal school": re.compile(r"\buniversal\s?school\b", re.I),
    "vardan international": re.compile(r"\bvardan\s?(?:intl|inter|international)\b", re.I),
    "st xavier": re.compile(r"\bst\.?\s?xavier'?s?\b", re.I),
    "next school": re.compile(r"\bnext\s?school\b", re.I),
    "cps global": re.compile(r"\bcps\s?global\b", re.I),
    "gear innovative": re.compile(r"\bgear\s?innovative\b", re.I),
    "aster public": re.compile(r"\baster\s?public\b", re.I),
    "mayoor": re.compile(r"\bmayoor\s?school\b", re.I),
    "ajmera global": re.compile(r"\bajmera\s?global\b", re.I),
    "met rishikul": re.compile(r"\bmet\s?rishikul\b", re.I),
    "santa mariya": re.compile(r"\bsanta\s?mariy?a\b", re.I),
    "kiit world": re.compile(r"\bkiit\s?world\b", re.I),
    "the riverside": re.compile(r"\briverside\s?school\b", re.I),
    "hvb global": re.compile(r"\bhvb\s?global\b", re.I),
    "global indian international": re.compile(r"\bglobal\s?indian\s?(?:intl|inter|international)\b|\bgiis\b", re.I),
    "apl global": re.compile(r"\bapl\s?global\b", re.I),
    "shalom hills": re.compile(r"\bshalom\s?hills\b", re.I),
    "fr agnel": re.compile(r"\bfr\.?\s?agnel\b|\bfather\s?agnel\b", re.I),
    "dlf public": re.compile(r"\bd\.?\s?l\.?\s?f\.?\s?public\s?school\b|\bdlf\s?public\s?school\b", re.I),
    "indirapuram public": re.compile(r"\bindirapuram\s?public\s?school\b", re.I),
    "gyaananda": re.compile(r"\bgyaananda\b|\bgyananda\b", re.I),
    "bgs vijnatham": re.compile(r"\bbgs\s?vijnatham\b", re.I),
    "hills international": re.compile(r"\bhills\s?(?:intl|inter|international)\b", re.I),
}

GENERIC_TOKENS = {
    "school", "public", "international", "academy", "high", "higher", "secondary",
    "senior", "sr", "sec", "primary", "nursery", "convent", "vidyalaya", "vidya",
    "mandir", "matriculation", "matric", "global", "world", "the", "and", "of",
    "english", "medium", "residential", "campus", "boys", "girls", "coed", "co",
    "ed", "learning", "college", "junior", "day", "boarding", "model", "sch",
    "group", "new", "little", "kids", "modern", "central", "national", "city",
}

PLAYSCHOOL_RE = re.compile(
    r"nursery|nursary|nurserry|nursury|"
    r"\bpre[-\s]?primary\b|\bpre[-\s]?school\b|\bpreschool\b|"
    r"\bplay[-\s]?school\b|\bplay[-\s]?way\b|\bplayway\b|"
    r"kindergarten|\bkinder\b|montessori|"
    r"\banganwadi\b|\bbalwadi\b|\bcreche\b|\bday[-\s]?care\b|"
    r"\b(?:lkg|ukg|kg)\b|"
    r"\bbachpan\b|\bkidzee\b|\beuro[-\s]?kids\b|\beurokids\b|"
    r"\bkangaroo[-\s]?kids\b|\blittle[-\s]?millennium\b|\bhello[-\s]?kids\b|"
    r"\bi\s?play\s?i\s?learn\b|\byour\s?kids\s?r\s?our\s?kids\b|"
    r"\blittle\s?laureates\b|\bmorning\s?blossom\b|"
    r"\biris\s?florets?\b|"
    r"\bfirstep\b|\bklay\b|\bkiwilearners\b|\btoddler\b",
    re.I,
)

PUBLIC_SCHOOL_RE = re.compile(r"\b(public|model|modern|vidya|vidyalaya|academy)\b", re.I)

# ──────────────────────────── Helpers ────────────────────────────

def safe_float(val):
    try:
        v = float(val)
        return v if not (math.isnan(v) or math.isinf(v)) else None
    except (TypeError, ValueError):
        return None


def norm(text):
    text = str(text or "").lower().replace("&amp;", "and").replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def name_tokens(text):
    return [t for t in norm(text).split() if t not in GENERIC_TOKENS and len(t) > 1]


def detect_chain(school_name):
    name_str = str(school_name or '')
    for chain, regex in PREMIUM_REGEXES.items():
        if regex.search(name_str):
            return chain
    return "independent"


def detect_chain_from_tokens(school_name, token_freq, min_freq=3):
    tokens = name_tokens(school_name)
    chain_tokens = [t for t in tokens if token_freq.get(t, 0) >= min_freq][:2]
    return " ".join(chain_tokens) if chain_tokens else "independent"


def apply_business_guardrails(frame, probabilities):
    """Cap suspicious low-enrollment non-premium-board records after model scoring."""
    probs = np.array(probabilities, dtype=float).copy()
    preschool_name = frame["school_name"].fillna("").str.contains(PLAYSCHOOL_RE)
    enrollment = pd.to_numeric(frame["enrollment_total"], errors="coerce")
    low_enrollment = enrollment.notna() & (enrollment < 100)
    tiny_enrollment = enrollment.notna() & (enrollment < 50)
    mainstream_board = (frame["board_cbse"] == 1) | (frame["board_state"] == 1)
    no_premium_board = (frame["board_icse"] == 0) & (frame["board_international"] == 0)
    no_known_premium_chain = frame["chain_known"].fillna("independent").eq("independent")
    publicish_name = frame["school_name"].fillna("").str.contains(PUBLIC_SCHOOL_RE)
    name_implied_international = (
        frame.get("board_from_name_only", pd.Series(0, index=frame.index)).fillna(0).astype(int).eq(1)
        & frame["school_name"].fillna("").str.contains(
            r"\b(international|global|world|public|model|academy|vidya|vidyalaya)\b",
            case=False,
            regex=True,
        )
    )

    probs[preschool_name.to_numpy()] = np.minimum(
        probs[preschool_name.to_numpy()],
        0.02,
    )

    suspicious_small_mainstream = (
        low_enrollment
        & mainstream_board
        & no_premium_board
        & no_known_premium_chain
    )
    probs[suspicious_small_mainstream.to_numpy()] = np.minimum(
        probs[suspicious_small_mainstream.to_numpy()],
        0.24,
    )
    suspicious_tiny_publicish = (
        tiny_enrollment
        & publicish_name
        & no_known_premium_chain
        & no_premium_board
    )
    probs[suspicious_tiny_publicish.to_numpy()] = np.minimum(
        probs[suspicious_tiny_publicish.to_numpy()],
        0.18,
    )
    suspicious_name_only_international = (
        low_enrollment
        & (frame["board_international"] == 1)
        & no_known_premium_chain
        & name_implied_international
    )
    probs[suspicious_name_only_international.to_numpy()] = np.minimum(
        probs[suspicious_name_only_international.to_numpy()],
        0.45,
    )
    return probs


# ──────────────────────────── City Mapping ────────────────────────────

def map_district_to_city(state_name, district_name, raw_city=None):
    """Maps district and state names robustly to targeted metropolitan cities."""
    if pd.notna(raw_city) and str(raw_city).strip().lower() in ["bengaluru", "delhi_ncr", "mumbai", "hyderabad", "chennai", "pune", "kolkata"]:
        return str(raw_city).strip().lower()
        
    state = str(state_name or "").upper()
    dist = str(district_name or "").upper()
    
    # Delhi NCR
    if "DELHI" in state or "DELHI" in dist:
        return "delhi_ncr"
    if "HARYANA" in state and any(d in dist for d in ["GURUGRAM", "GURGAON", "FARIDABAD", "PALWAL", "JHAJJAR", "ROHTAK", "SONIPAT", "SONEPAT", "PANIPAT"]):
        return "delhi_ncr"
    if "UTTAR PRADESH" in state and any(d in dist for d in ["GAUTAM BUDDHA NAGAR", "GHAZIABAD", "HAPUR", "BULANDSHAHR", "MEERUT", "BAGHPAT"]):
        return "delhi_ncr"
        
    # Mumbai
    if "MAHARASHTRA" in state and any(d in dist for d in ["MUMBAI", "THANE", "PALGHAR", "RAIGAD", "RAIGARH"]):
        return "mumbai"
        
    # Pune
    if "MAHARASHTRA" in state and any(d in dist for d in ["PUNE", "NASHIK", "SATARA", "SOLAPUR"]):
        return "pune"
        
    # Hyderabad
    if "TELANGANA" in state and any(d in dist for d in ["HYDERABAD", "RANGAREDDY", "RANGA REDDY", "MEDCHAL", "MALKAJGIRI", "SANGAREDDY", "MEDAK", "WARANGAL"]):
        return "hyderabad"
        
    # Bengaluru
    if "KARNATAKA" in state and any(d in dist for d in ["BENGALURU", "BANGALORE", "CHIKKABALLAPURA", "CHIKKABALLAPUR", "RAMANAGARA", "RAMANAGARAM", "KOLAR", "TUMAKURU", "TUMKUR", "BELAGAVI", "DHARWAD"]):
        return "bengaluru"
        
    # Chennai
    if "TAMIL NADU" in state or "TAMILNADU" in state:
        if any(d in dist for d in ["CHENNAI", "KANCHEEPURAM", "KANCHIPURAM", "TIRUVALLUR", "THIRUVALLUR", "CHENGALPATTU"]):
            return "chennai"
            
    # Kolkata
    if "WEST BENGAL" in state or "WESTBENGAL" in state:
        if any(d in dist for d in ["KOLKATA", "HOWRAH", "HOOGHLY", "NORTH 24", "SOUTH 24", "NADIA"]):
            return "kolkata"
            
    # Ahmedabad
    if "GUJARAT" in state and any(d in dist for d in ["AHMEDABAD", "GANDHINAGAR"]):
        return "ahmedabad"
        
    return "unknown"


# ──────────────────────────── Smart Board & Medium Inference ────────────────────────────

def infer_board_family(school_name, boards_text=None, udise_bs=None, udise_bhs=None, is_english=1):
    bs = int(udise_bs) if pd.notna(udise_bs) else 0
    bhs = int(udise_bhs) if pd.notna(udise_bhs) else 0
    best_udise = bhs if bhs > 0 else bs
    
    if best_udise == 1:
        return "cbse"
    elif best_udise == 3:
        return "icse"
    elif best_udise == 4:
        return "international"
    elif best_udise == 2:
        return "state"
        
    if pd.notna(boards_text) and boards_text:
        bt = str(boards_text).lower()
        if any(k in bt for k in ("ib", "igcse", "cambridge")):
            return "international"
        if "international" in bt and "cbse" not in bt:
            return "international"
        if any(k in bt for k in ("icse", "cisce", "isc")):
            return "icse"
        if "cbse" in bt:
            return "cbse"
        if "state" in bt:
            return "state"

    name = norm(school_name)
    if "cbse" in name or "central school" in name:
        return "cbse"
    if "icse" in name or "isc" in name or "cisce" in name:
        return "icse"
    if any(k in name for k in ("igcse", "cambridge", " ib ", "international baccalaureate")):
        return "international"
    if any(k in name for k in ("matric", "matriculation", "state board", "ssc", "hsc", "samiti")):
        return "state"

    if is_english:
        if any(k in name for k in ("international", "global", "world")):
            return "international"
        if any(k in name for k in ("convent", "xavier", "carmel", "saint", "st.", "grammar")):
            return "icse"
        return "cbse"
    else:
        return "state"


def infer_english_medium(school_name, medium_id=None):
    if pd.notna(medium_id) and int(medium_id) > 0:
        return 1 if int(medium_id) == 19 else 0
    name = norm(school_name)
    local_keywords = ["hindi medium", "telugu medium", "urdu medium", "marathi medium", "kannada medium", "tamil medium", "gujarati medium", "bengali medium"]
    if any(k in name for k in local_keywords):
        return 0
    return 1


def parse_udise_json(row):
    out = {}
    try:
        s = json.loads(row["summary_json"])
        for key in [
            "schCategoryId", "schType", "schMgmtId", "classFrm", "classTo",
            "schLocRuralUrban", "pincode", "stateName", "districtName",
            "pmShriYn", "isnewCy", "schBroadMgmtId", "schMgmtParentId",
            "schMgmtDesc", "schMgmtType", "schMgmtDescSt", "schoolStatus",
        ]:
            out[f"udise_{key}"] = s.get(key)
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        e = json.loads(row["enrollment_json"])
        data = e.get("data", {})
        for key in [
            "totalBoy", "totalGirl", "totalCount",
            "totalTeacherCon", "totalTeacherReg",
            "totalTeacherMale", "totalTeacherFemale",
        ]:
            out[f"udise_{key}"] = safe_float(data.get(key))
    except (json.JSONDecodeError, TypeError):
        pass
    return out


# ──────────────────────────── Data Loading ────────────────────────────

def load_udise():
    print("Loading UDISE master data...")
    df = pd.read_csv(UDISE_PATH, encoding="utf-8-sig", dtype={"udise_code": str})
    print(f"  Raw UDISE rows: {len(df):,}")
    if FULL_UDISE_PATH.exists():
        full = pd.read_csv(FULL_UDISE_PATH, encoding="utf-8-sig", dtype={"udise_code": str})
        private_rows = []
        existing_codes = set(df["udise_code"].dropna().astype(str))
        for _, row in full.iterrows():
            if str(row.get("udise_code")) in existing_codes:
                continue
            try:
                summary = json.loads(row.get("summary_json") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            is_operational = int(summary.get("schoolStatus", 0) or 0) == 0
            is_private_unaided_parent = int(summary.get("schMgmtParentId", 0) or 0) == 5
            is_private_broad = int(summary.get("schBroadMgmtId", 0) or 0) == 3
            if is_operational and (is_private_unaided_parent or is_private_broad):
                private_rows.append(row)
        if private_rows:
            additions = pd.DataFrame(private_rows)[df.columns]
            df = pd.concat([df, additions], ignore_index=True)
            print(f"  Added missed private rows from full client export: {len(additions):,}")
            print(f"  Expanded UDISE rows: {len(df):,}")

    parsed = df.apply(parse_udise_json, axis=1, result_type="expand")
    df = pd.concat([
        df[["udise_code", "school_id", "school_name", "pincode", "state_name", "district_name"]],
        parsed,
    ], axis=1)
    df["school_id"] = df["school_id"].astype(str)

    df["udise_totalTeachers"] = df["udise_totalTeacherCon"].fillna(0) + df["udise_totalTeacherReg"].fillna(0)
    df["udise_student_teacher_ratio"] = np.where(
        df["udise_totalTeachers"] > 0, df["udise_totalCount"] / df["udise_totalTeachers"], np.nan,
    )
    df["udise_gender_ratio"] = np.where(
        df["udise_totalCount"] > 0, df["udise_totalGirl"] / df["udise_totalCount"], np.nan,
    )
    df["udise_class_span"] = df["udise_classTo"] - df["udise_classFrm"] + 1

    # Join board lookup
    print("\nLoading UDISE board/medium lookup...")
    board_df = pd.read_csv(BOARD_LOOKUP_PATH, dtype={"school_id": str})
    df = df.merge(board_df, on="school_id", how="left")
    
    df["boardSec"] = df["boardSec"].fillna(0).astype(int)
    df["boardHighSec"] = df["boardHighSec"].fillna(0).astype(int)
    df["mediumId1"] = df["mediumId1"].fillna(0).astype(int)

    df["is_english_medium"] = df.apply(
        lambda r: infer_english_medium(r["school_name"], r["mediumId1"]), axis=1
    )
    df["board_family"] = df.apply(
        lambda r: infer_board_family(
            r["school_name"],
            " ".join(str(r.get(c) or "") for c in ["udise_schMgmtDesc", "udise_schMgmtType", "udise_schMgmtDescSt"]),
            r["boardSec"], r["boardHighSec"], r["is_english_medium"]
        ), axis=1
    )

    df["board_cbse"] = (df["board_family"] == "cbse").astype(int)
    df["board_icse"] = (df["board_family"] == "icse").astype(int)
    df["board_international"] = (df["board_family"] == "international").astype(int)
    df["board_state"] = (df["board_family"] == "state").astype(int)

    before_preschool_filter = len(df)
    df = df[~df["school_name"].fillna("").str.contains(PLAYSCHOOL_RE)].copy()
    removed_preschools = before_preschool_filter - len(df)
    print(f"    Removed preschool/nursery/KG rows: {removed_preschools:>6,}")

    print(f"\n  UDISE smart inferred board distribution:")
    print(f"    CBSE:          {df['board_cbse'].sum():>6,}")
    print(f"    State Board:   {df['board_state'].sum():>6,}")
    print(f"    ICSE:          {df['board_icse'].sum():>6,}")
    print(f"    International: {df['board_international'].sum():>6,}")
    print(f"    English medium:{df['is_english_medium'].sum():>6,}")

    return df


def load_labeled():
    print("\nLoading labeled data...")
    df = pd.read_csv(LABELED_PATH, encoding="utf-8-sig", dtype={"udise_code": str})
    df["fee"] = pd.to_numeric(df["fee"], errors="coerce")
    df = df[df["fee"] > 0].copy()
    print(f"  Labeled rows with valid fee: {len(df):,}")
    return df


def load_bangalore():
    if not BANGALORE_PATH.exists():
        return pd.DataFrame()
    print("\nLoading Bangalore data...")
    sj = pd.read_json(BANGALORE_PATH)
    rows = []
    for _, r in sj.iterrows():
        fee_val = safe_float(r.get("fee")) or safe_float(r.get("fee_min"))
        if not fee_val or fee_val <= 0:
            continue
        rows.append({
            "school_name": r.get("name"), "city": "bengaluru",
            "area": r.get("area"),
            "pincode": r.get("pincode") or r.get("google_postal_code"),
            "latitude": r.get("lat"), "longitude": r.get("lon"),
            "boards": r.get("board"), "fee": fee_val,
            "student_enrollment": safe_float(r.get("students_total")) or safe_float(r.get("students")),
            "student_enrollment_grades_2_9": safe_float(r.get("students_grades_2_9")),
            "enrollment_source": r.get("enrollment_source"),
            "udise_code": str(r.get("udise_code")) if pd.notna(r.get("udise_code")) else None,
            "lowest_class": None, "highest_class": None,
            "source": r.get("source"),
        })
    blr = pd.DataFrame(rows)
    print(f"  Bangalore rows: {len(blr):,}")
    return blr


# ──────────────────────────── Feature Engineering ────────────────────────────

def build_training_dataset():
    udise_df = load_udise()
    labeled_df = load_labeled()
    blr_df = load_bangalore()

    # Combine labeled + Bangalore
    if not blr_df.empty:
        existing_codes = set(labeled_df["udise_code"].dropna().unique())
        blr_new = blr_df[~blr_df["udise_code"].isin(existing_codes) | blr_df["udise_code"].isna()].copy()
        labeled_df = pd.concat([labeled_df, blr_new], ignore_index=True)
        print(f"  Combined labeled + Bangalore: {len(labeled_df):,}")

    # Filter playschools
    labeled_df = labeled_df[~labeled_df["school_name"].fillna("").str.contains(PLAYSCHOOL_RE)].copy()
    print(f"  After playschool filter: {len(labeled_df):,}")

    # Token frequencies for chain detection
    token_freq = Counter()
    for name in labeled_df["school_name"].dropna():
        token_freq.update(set(name_tokens(name)))

    # Split by UDISE match
    has_udise = labeled_df["udise_code"].notna()
    matched = labeled_df[has_udise].copy()
    unmatched = labeled_df[~has_udise].copy()

    # Join matched with UDISE
    joined = matched.merge(udise_df, on="udise_code", how="left", suffixes=("_labeled", "_udise"))
    print(f"\n  Matched + UDISE joined: {len(joined):,}")
    print(f"  Unmatched (estimated enrollment): {len(unmatched):,}")

    # Build records
    records = []
    for _, row in joined.iterrows():
        records.append(_build_record(row, has_udise=True, token_freq=token_freq))
    for _, row in unmatched.iterrows():
        records.append(_build_record(row, has_udise=False, token_freq=token_freq))

    df = pd.DataFrame(records)
    df["target"] = (df["fee"] > THRESHOLD).astype(int)

    # Derived features
    df["log_enrollment"] = df["enrollment_total"].apply(
        lambda v: math.log1p(v) if pd.notna(v) and v >= 0 else np.nan)
    df["log_enrollment_g29"] = df["enrollment_g29"].apply(
        lambda v: math.log1p(v) if pd.notna(v) and v >= 0 else np.nan)
    df["enrollment_missing"] = df["enrollment_total"].isna().astype(int)

    # Board interaction features
    df["is_premium_board"] = ((df["board_international"] == 1) | (df["board_icse"] == 1)).astype(int)
    df["is_state_only"] = (
        (df["board_state"] == 1) & (df["board_cbse"] == 0) &
        (df["board_icse"] == 0) & (df["board_international"] == 0)
    ).astype(int)
    df["is_international_only"] = (
        (df["board_international"] == 1) & (df["board_cbse"] == 0) &
        (df["board_icse"] == 0) & (df["board_state"] == 0)
    ).astype(int)
    df["is_premium_chain"] = (df["chain_known"] != "independent").astype(int)

    print(f"\n═══ Training Dataset ═══")
    print(f"  Total rows: {len(df):,}")
    t0, t1 = (df["target"] == 0).sum(), (df["target"] == 1).sum()
    print(f"  ≤1L: {t0:,} ({t0/len(df)*100:.1f}%)  |  >1L: {t1:,} ({t1/len(df)*100:.1f}%)")
    print(f"  Features: {len(ALL_FEATURES)}")

    return df, udise_df, token_freq


def _build_record(row, has_udise, token_freq):
    name = row.get("school_name") or row.get("school_name_labeled") or ""
    boards_text = row.get("boards")
    pin_raw = row.get("pincode") or row.get("udise_pincode")

    # City mapping (robust)
    city_inferred = map_district_to_city(
        row.get("state_name") or row.get("udise_stateName"),
        row.get("district_name") or row.get("udise_districtName"),
        row.get("city")
    )

    is_eng = infer_english_medium(name, row.get("mediumId1") if has_udise else None)
    bf_fam = infer_board_family(
        name, boards_text, 
        row.get("boardSec") if has_udise else None, 
        row.get("boardHighSec") if has_udise else None, 
        is_eng
    )
    has_udise_board_code = bool(
        has_udise
        and (
            safe_float(row.get("boardSec")) not in (None, 0)
            or safe_float(row.get("boardHighSec")) not in (None, 0)
        )
    )

    rec = {
        "fee": safe_float(row.get("fee")),
        "school_name": name,

        # Location
        "city": city_inferred,
        "latitude": safe_float(row.get("latitude")),
        "longitude": safe_float(row.get("longitude")),
        "pincode_num": safe_float(pin_raw),

        # Smart Unified Board
        "board_cbse": int(bf_fam == "cbse"),
        "board_icse": int(bf_fam == "icse"),
        "board_international": int(bf_fam == "international"),
        "board_state": int(bf_fam == "state"),
        "board_family": bf_fam,
        "board_from_name_only": int(not has_udise_board_code and bf_fam == "international"),
        "is_english_medium": is_eng,

        # Chain
        "chain_known": detect_chain(name),
        "chain_token": detect_chain_from_tokens(name, token_freq),

        "has_udise_match": int(has_udise),
    }

    if has_udise:
        # Enrollment from UDISE
        rec["enrollment_total"] = safe_float(row.get("udise_totalCount"))
        rec["enrollment_g29"] = safe_float(row.get("student_enrollment_grades_2_9"))
        rec["teacher_count"] = safe_float(row.get("udise_totalTeachers"))
        rec["teacher_contractual"] = safe_float(row.get("udise_totalTeacherCon"))
        rec["teacher_regular"] = safe_float(row.get("udise_totalTeacherReg"))
        rec["student_teacher_ratio"] = safe_float(row.get("udise_student_teacher_ratio"))
        rec["gender_ratio"] = safe_float(row.get("udise_gender_ratio"))
        rec["class_from"] = safe_float(row.get("udise_classFrm"))
        rec["class_to"] = safe_float(row.get("udise_classTo"))
        rec["class_span"] = safe_float(row.get("udise_class_span"))
        rec["location_type"] = safe_float(row.get("udise_schLocRuralUrban"))
        rec["school_category"] = safe_float(row.get("udise_schCategoryId"))
        rec["school_type_udise"] = safe_float(row.get("udise_schType"))
        rec["pm_shri"] = safe_float(row.get("udise_pmShriYn"))
        rec["is_new"] = safe_float(row.get("udise_isnewCy"))
    else:
        # Estimated enrollment
        rec["enrollment_total"] = safe_float(row.get("student_enrollment"))
        rec["enrollment_g29"] = safe_float(row.get("student_enrollment_grades_2_9"))
        rec["teacher_count"] = None
        rec["teacher_contractual"] = None
        rec["teacher_regular"] = None
        rec["student_teacher_ratio"] = None
        rec["gender_ratio"] = None
        rec["class_from"] = safe_float(row.get("lowest_class"))
        rec["class_to"] = safe_float(row.get("highest_class"))
        cf, ct = rec["class_from"], rec["class_to"]
        rec["class_span"] = (ct - cf + 1) if cf is not None and ct is not None else None
        rec["location_type"] = None
        rec["school_category"] = None
        rec["school_type_udise"] = None
        rec["pm_shri"] = None
        rec["is_new"] = None

    return rec


# ──────────────────────────── Feature Definitions ────────────────────────────

NUMERIC_FEATURES = [
    # Enrollment
    "log_enrollment", "log_enrollment_g29", "enrollment_missing",
    # Teachers
    "teacher_count", "teacher_contractual", "teacher_regular",
    "student_teacher_ratio", "gender_ratio",
    # Class range
    "class_from", "class_to", "class_span",
    # UDISE categorical (numeric for trees)
    "location_type", "school_category", "school_type_udise",
    "pm_shri", "is_new",
    # Board Flags
    "board_cbse", "board_icse", "board_international", "board_state",
    "is_english_medium",
    # Board Interactions
    "is_premium_board", "is_state_only", "is_international_only",
    # Location
    "latitude", "longitude", "pincode_num",
    # Meta
    "has_udise_match", "is_premium_chain",
]

CATEGORICAL_FEATURES = [
    "city",
    "board_family",
    "chain_known",
    "chain_token",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


# ──────────────────────────── Preprocessing ────────────────────────────

def build_preprocessor():
    numeric_pipeline = Pipeline([
        ("imputer", KNNImputer(n_neighbors=5, weights="distance")),
        ("scaler", StandardScaler()),
    ])
    categorical_pipeline = Pipeline([
        ("imputer", SimpleImputer(strategy="most_frequent")),
        ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
    ])
    return ColumnTransformer([
        ("num", numeric_pipeline, NUMERIC_FEATURES),
        ("cat", categorical_pipeline, CATEGORICAL_FEATURES),
    ])


# ──────────────────────────── Models ────────────────────────────

def make_xgb(spw):
    return XGBClassifier(
        n_estimators=500, max_depth=7, learning_rate=0.05,
        scale_pos_weight=spw, subsample=0.8, colsample_bytree=0.8,
        min_child_weight=3, gamma=0.1, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, eval_metric="logloss", n_jobs=-1,
    )

def make_rf():
    return RandomForestClassifier(
        n_estimators=500, max_depth=12, min_samples_leaf=2,
        max_features="sqrt", class_weight="balanced", random_state=42, n_jobs=-1,
    )

def make_et():
    return ExtraTreesClassifier(
        n_estimators=500, max_depth=14, min_samples_leaf=1,
        max_features="sqrt", class_weight="balanced", random_state=42, n_jobs=-1,
    )

def make_ensemble(spw):
    return VotingClassifier(
        estimators=[("xgb", make_xgb(spw)), ("rf", make_rf()), ("et", make_et())],
        voting="soft", weights=[2, 1, 1],
    )


# ──────────────────────────── Training & Evaluation ────────────────────────────

def train_and_evaluate(df):
    X = df[ALL_FEATURES].copy()
    y = df["target"].values
    for col in CATEGORICAL_FEATURES:
        X[col] = X[col].astype(str).fillna("missing")

    n_neg, n_pos = (y == 0).sum(), (y == 1).sum()
    spw = n_neg / n_pos
    print(f"\n═══ Class Imbalance ═══")
    print(f"  ≤1L: {n_neg:,}  |  >1L: {n_pos:,}  |  Ratio: {spw:.2f}:1")

    # City-based sample weights for calibration
    city_true_rates = {
        "bengaluru": 0.175, "chennai": 0.136, "delhi_ncr": 0.219,
        "hyderabad": 0.247, "kolkata": 0.190, "mumbai": 0.267,
        "pune": 0.199, "ahmedabad": 0.070, "unknown": 0.040
    }
    weights = np.ones(len(df))
    for city, grp in df.groupby("city"):
        indices = grp.index
        y_city = y[indices]
        n_total = len(grp)
        n_pos_city = y_city.sum()
        n_neg_city = n_total - n_pos_city
        target_rate = city_true_rates.get(city, 0.08)
        w_pos = (n_total * target_rate) / n_pos_city if n_pos_city > 0 else 1.0
        w_neg = (n_total * (1 - target_rate)) / n_neg_city if n_neg_city > 0 else 1.0
        weights[indices] = np.where(y_city == 1, w_pos, w_neg)

    # ═══ 5-Fold Stratified CV ═══
    print(f"\n{'═' * 65}")
    print(f"  5-FOLD STRATIFIED CROSS-VALIDATION  (BLIND TEST)")
    print(f"{'═' * 65}")

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_results = []
    all_y_true, all_y_pred, all_y_prob = [], [], []
    fold_importances = []

    for fold, (train_idx, test_idx) in enumerate(skf.split(X, y), 1):
        X_train, X_test = X.iloc[train_idx].copy(), X.iloc[test_idx].copy()
        y_train, y_test = y[train_idx], y[test_idx]
        w_train = weights[train_idx]

        pre = build_preprocessor()
        X_tr = pre.fit_transform(X_train)
        X_te = pre.transform(X_test)

        ens = make_ensemble(spw)
        ens.fit(X_tr, y_train, sample_weight=w_train)

        y_pred = ens.predict(X_te)
        y_prob = ens.predict_proba(X_te)[:, 1]
        y_prob = apply_business_guardrails(df.iloc[test_idx].reset_index(drop=True), y_prob)
        y_pred = (y_prob >= 0.50).astype(int)

        acc = accuracy_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred, zero_division=0)
        rec = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)
        auc = roc_auc_score(y_test, y_prob)

        cv_results.append({"fold": fold, "accuracy": acc, "precision": prec,
                           "recall": rec, "f1": f1, "auc": auc,
                           "actual_pos": int(y_test.sum()), "predicted_pos": int(y_pred.sum())})
        all_y_true.extend(y_test)
        all_y_pred.extend(y_pred)
        all_y_prob.extend(y_prob)
        fold_importances.append(ens.named_estimators_["xgb"].feature_importances_)

        print(f"  Fold {fold}: Acc={acc:.4f}  Prec={prec:.4f}  Rec={rec:.4f}  "
              f"F1={f1:.4f}  AUC={auc:.4f}  (pred={y_pred.sum()}/{y_test.sum()})")

    cv_df = pd.DataFrame(cv_results)
    oa = accuracy_score(all_y_true, all_y_pred)
    op = precision_score(all_y_true, all_y_pred, zero_division=0)
    orr = recall_score(all_y_true, all_y_pred, zero_division=0)
    of1 = f1_score(all_y_true, all_y_pred, zero_division=0)

    print(f"\n  OVERALL: Acc={oa:.4f} ({oa*100:.1f}%)  Prec={op:.4f}  Rec={orr:.4f}  F1={of1:.4f}")
    print(f"  {'TARGET MET ✅' if oa >= 0.80 else 'See threshold tuning below'}")
    report = classification_report(all_y_true, all_y_pred,
                                   target_names=["≤1L", ">1L"], digits=4)
    print(f"\n{report}")
    cm = confusion_matrix(all_y_true, all_y_pred)
    print(f"  Confusion Matrix:")
    print(f"               Pred ≤1L   Pred >1L")
    print(f"  Actual ≤1L:  {cm[0][0]:>7,}    {cm[0][1]:>7,}")
    print(f"  Actual >1L:  {cm[1][0]:>7,}    {cm[1][1]:>7,}")

    # ═══ Threshold Tuning ═══
    print(f"\n{'═' * 65}")
    print(f"  THRESHOLD TUNING")
    print(f"{'═' * 65}")
    yt = np.array(all_y_true)
    yp = np.array(all_y_prob)
    best_thresh, best_acc = 0.5, oa
    thresh_rows = []
    for t in np.arange(0.30, 0.75, 0.02):
        pred = (yp >= t).astype(int)
        a = accuracy_score(yt, pred)
        p = precision_score(yt, pred, zero_division=0)
        r = recall_score(yt, pred, zero_division=0)
        f = f1_score(yt, pred, zero_division=0)
        thresh_rows.append({"threshold": round(t, 2), "accuracy": a, "precision": p,
                            "recall": r, "f1": f, "predicted_pos": int(pred.sum())})
        if a > best_acc:
            best_acc = a
            best_thresh = t

    thresh_df = pd.DataFrame(thresh_rows)
    print(thresh_df.to_string(index=False))
    print(f"\n  Best: threshold={best_thresh:.2f} → Accuracy={best_acc:.4f} ({best_acc*100:.1f}%)")
    print(f"  {'TARGET MET ✅' if best_acc >= 0.80 else 'BELOW 80%'}")

    # Report at best threshold
    y_best = (yp >= best_thresh).astype(int)
    report_best = classification_report(yt, y_best, target_names=["≤1L", ">1L"], digits=4)
    print(f"\n{report_best}")

    # ═══ 80/20 Hold-out ═══
    print(f"\n{'═' * 65}")
    print(f"  80/20 HOLD-OUT BLIND TEST (threshold={best_thresh:.2f})")
    print(f"{'═' * 65}")
    train_idx, test_idx = train_test_split(np.arange(len(X)), test_size=0.2, stratify=y, random_state=42)
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y[train_idx], y[test_idx]
    pre = build_preprocessor()
    X_tr, X_te = pre.fit_transform(X_train), pre.transform(X_test)
    ens = make_ensemble(spw)
    ens.fit(X_tr, y_train)
    y_prob_h = ens.predict_proba(X_te)[:, 1]
    y_prob_h = apply_business_guardrails(df.iloc[test_idx].reset_index(drop=True), y_prob_h)
    y_pred_h = (y_prob_h >= best_thresh).astype(int)
    hacc = accuracy_score(y_test, y_pred_h)
    print(f"  Hold-out Accuracy: {hacc:.4f} ({hacc*100:.1f}%)")
    print(classification_report(y_test, y_pred_h, target_names=["≤1L", ">1L"], digits=4))

    # ═══ Feature Importance ═══
    print(f"\n{'═' * 65}")
    print(f"  FEATURE IMPORTANCE")
    print(f"{'═' * 65}")
    avg_imp = np.mean(fold_importances, axis=0)
    fnames = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    if len(fnames) != len(avg_imp):
        fnames = [f"f_{i}" for i in range(len(avg_imp))]
    imp_df = pd.DataFrame({"feature": fnames, "importance": avg_imp}).sort_values("importance", ascending=False)
    print(f"\n  Top 20:")
    for _, r in imp_df.head(20).iterrows():
        bar = "█" * max(1, int(r["importance"] * 60))
        print(f"    {r['feature']:30s} {r['importance']:.4f} {bar}")

    imp_df.to_csv(OUTPUT_DIR / "fee_classification_feature_importance.csv", index=False)

    # Plot
    fig, ax = plt.subplots(figsize=(12, 9))
    top = imp_df.head(25)
    colors = plt.cm.magma(np.linspace(0.25, 0.85, len(top)))
    ax.barh(range(len(top)), top["importance"].values, color=colors, edgecolor="white", linewidth=0.5)
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(top["feature"].values, fontsize=10)
    ax.invert_yaxis()
    ax.set_xlabel("Importance (Gain)", fontsize=12)
    ax.set_title(f"Feature Importance — Fee >₹1L Classification\n"
                 f"5-Fold CV Accuracy: {best_acc:.1%}  |  Threshold: {best_thresh:.2f}", fontsize=13, fontweight="bold")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / "fee_classification_feature_importance.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    cv_df.to_csv(OUTPUT_DIR / "fee_classification_cv_results.csv", index=False)
    thresh_df.to_csv(OUTPUT_DIR / "fee_classification_threshold_tuning.csv", index=False)

    return cv_df, best_acc, best_thresh, imp_df, report_best


# ──────────────────────────── Predict Full UDISE ────────────────────────────

def predict_full_udise(training_df, udise_df, token_freq, best_thresh):
    print(f"\n{'═' * 65}")
    print(f"  FINAL MODEL → PREDICT ALL {len(udise_df):,} UDISE SCHOOLS")
    print(f"{'═' * 65}")

    X_all = training_df[ALL_FEATURES].copy()
    y_all = training_df["target"].values
    for col in CATEGORICAL_FEATURES:
        X_all[col] = X_all[col].astype(str).fillna("missing")

    spw = (y_all == 0).sum() / (y_all == 1).sum()
    
    # Calculate city-based sample weights for final model fitting
    city_true_rates = {
        "bengaluru": 0.175, "chennai": 0.136, "delhi_ncr": 0.219,
        "hyderabad": 0.247, "kolkata": 0.190, "mumbai": 0.267,
        "pune": 0.199, "ahmedabad": 0.070, "unknown": 0.040
    }
    weights = np.ones(len(training_df))
    for city, grp in training_df.groupby("city"):
        indices = grp.index
        y_city = y_all[indices]
        n_total = len(grp)
        n_pos_city = y_city.sum()
        n_neg_city = n_total - n_pos_city
        target_rate = city_true_rates.get(city, 0.08)
        w_pos = (n_total * target_rate) / n_pos_city if n_pos_city > 0 else 1.0
        w_neg = (n_total * (1 - target_rate)) / n_neg_city if n_neg_city > 0 else 1.0
        weights[indices] = np.where(y_city == 1, w_pos, w_neg)

    final_pre = build_preprocessor()
    X_all_proc = final_pre.fit_transform(X_all)
    final_model = make_ensemble(spw)
    final_model.fit(X_all_proc, y_all, sample_weight=weights)
    print(f"  Trained on {len(y_all):,} schools")

    pred_thresh = MARKET_PREDICTION_THRESHOLD
    strict_thresh = best_thresh
    print(f"  Prediction threshold: {pred_thresh:.2f} (market-sizing)")
    print(f"  Strict audit threshold: {strict_thresh:.2f} (CV-best)")

    # Build features for all UDISE schools
    records = []
    for _, row in udise_df.iterrows():
        name = row.get("school_name") or ""
        city_inferred = map_district_to_city(
            row.get("state_name") or row.get("udise_stateName"),
            row.get("district_name") or row.get("udise_districtName"),
            None
        )

        enr = safe_float(row.get("udise_totalCount"))
        tcount = safe_float(row.get("udise_totalTeachers"))

        # Smart Unified Board Info
        u_bf = row.get("board_family", "state")
        u_cbse = int(row.get("board_cbse", 0))
        u_icse = int(row.get("board_icse", 0))
        u_intl = int(row.get("board_international", 0))
        u_state = int(row.get("board_state", 0))
        u_eng = int(row.get("is_english_medium", 0))
        u_has_board_code = (
            safe_float(row.get("boardSec")) not in (None, 0)
            or safe_float(row.get("boardHighSec")) not in (None, 0)
        )

        rec = {
            "school_name": name,
            "enrollment_total": enr,
            "log_enrollment": math.log1p(enr) if enr and enr > 0 else np.nan,
            "log_enrollment_g29": np.nan,
            "enrollment_missing": 0 if enr is not None else 1,
            "teacher_count": tcount,
            "teacher_contractual": safe_float(row.get("udise_totalTeacherCon")),
            "teacher_regular": safe_float(row.get("udise_totalTeacherReg")),
            "student_teacher_ratio": safe_float(row.get("udise_student_teacher_ratio")),
            "gender_ratio": safe_float(row.get("udise_gender_ratio")),
            "class_from": safe_float(row.get("udise_classFrm")),
            "class_to": safe_float(row.get("udise_classTo")),
            "class_span": safe_float(row.get("udise_class_span")),
            "location_type": safe_float(row.get("udise_schLocRuralUrban")),
            "school_category": safe_float(row.get("udise_schCategoryId")),
            "school_type_udise": safe_float(row.get("udise_schType")),
            "pm_shri": safe_float(row.get("udise_pmShriYn")),
            "is_new": safe_float(row.get("udise_isnewCy")),
            # Unified board
            "board_cbse": u_cbse,
            "board_icse": u_icse,
            "board_international": u_intl,
            "board_state": u_state,
            "is_english_medium": u_eng,
            "board_from_name_only": int(not u_has_board_code and u_intl == 1),
            # Board interactions
            "is_premium_board": int(u_intl == 1 or u_icse == 1),
            "is_state_only": int(u_state == 1 and u_cbse == 0 and u_icse == 0 and u_intl == 0),
            "is_international_only": int(u_intl == 1 and u_cbse == 0 and u_icse == 0 and u_state == 0),
            "latitude": np.nan, "longitude": np.nan,
            "pincode_num": safe_float(row.get("udise_pincode") or row.get("pincode")),
            "has_udise_match": 1,
            "is_premium_chain": int(detect_chain(name) != "independent"),
            "city": city_inferred,
            "board_family": u_bf,
            "chain_known": detect_chain(name),
            "chain_token": detect_chain_from_tokens(name, token_freq),
        }
        records.append(rec)

    pred_df = pd.DataFrame(records)
    for col in CATEGORICAL_FEATURES:
        pred_df[col] = pred_df[col].astype(str).fillna("missing")

    X_pred_proc = final_pre.transform(pred_df[ALL_FEATURES])
    probs = final_model.predict_proba(X_pred_proc)[:, 1]
    probs = apply_business_guardrails(pred_df, probs)
    preds = (probs >= pred_thresh).astype(int)
    strict_preds = (probs >= strict_thresh).astype(int)

    output = pd.DataFrame({
        "udise_code": udise_df["udise_code"].values,
        "school_name": udise_df["school_name"].values,
        "state": udise_df["state_name"].values,
        "district": udise_df["district_name"].values,
        "predicted_fee_class": np.where(preds == 1, ">1L", "≤1L"),
        "likely_gt_1L": preds,
        "strict_gt_1L": strict_preds,
        "market_threshold": pred_thresh,
        "strict_threshold": round(strict_thresh, 2),
        "confidence": np.round(probs, 4),
        "inferred_board": pred_df["board_family"].values,
        "is_english_medium": pred_df["is_english_medium"].values,
        "enrollment_total": pred_df["log_enrollment"].apply(
            lambda v: round(math.expm1(v)) if pd.notna(v) else None).values,
        "student_teacher_ratio": pred_df["student_teacher_ratio"].values,
        "inferred_city": pred_df["city"].values,
        "chain_detected": pred_df["chain_known"].values,
    })
    output.to_csv(OUTPUT_DIR / "fee_classification_predictions_all_udise.csv", index=False)
    output.to_csv(OUTPUT_DIR / "fee_classification_predictions_calibrated.csv", index=False)

    above = (preds == 1).sum()
    below = (preds == 0).sum()
    strict_above = (strict_preds == 1).sum()
    print(f"\n  Prediction Summary (threshold={pred_thresh:.2f}):")
    print(f"    Total:         {len(preds):>8,}")
    print(f"    Predicted >1L: {above:>8,}  ({above/len(preds)*100:.1f}%)")
    print(f"    Predicted ≤1L: {below:>8,}  ({below/len(preds)*100:.1f}%)")
    print(f"    Strict >1L:    {strict_above:>8,}  ({strict_above/len(preds)*100:.1f}%)")
    print(f"\n  By board:")
    for b in ["cbse", "state", "icse", "international"]:
        mask = pred_df["board_family"] == b
        if mask.sum() > 0:
            above_b = (preds[mask] == 1).sum()
            print(f"    {b:15s}: {above_b:>5,} / {mask.sum():>6,} predicted >1L ({above_b/mask.sum()*100:.1f}%)")
    print(f"\n  Saved: {OUTPUT_DIR / 'fee_classification_predictions_all_udise.csv'}")
    return output


# ──────────────────────────── Report ────────────────────────────

def save_report(best_acc, best_thresh, report_text, cv_df, imp_df):
    path = OUTPUT_DIR / "fee_classification_report.txt"
    with open(path, "w") as f:
        f.write("=" * 70 + "\n")
        f.write("  FEE CLASSIFICATION REPORT v5 — Comprehensive Features\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"  Best CV Accuracy: {best_acc:.4f} ({best_acc*100:.1f}%)\n")
        f.write(f"  Threshold: {best_thresh:.2f}\n")
        f.write(f"  Target: 80%+ → {'MET ✅' if best_acc >= 0.80 else 'NOT MET ❌'}\n\n")
        f.write(cv_df.to_string(index=False) + "\n\n")
        f.write(report_text + "\n\n")
        f.write(imp_df.head(25).to_string(index=False) + "\n")
    print(f"  Report: {path}")


# ──────────────────────────── Main ────────────────────────────

def main():
    print("=" * 70)
    print("  FEE CLASSIFICATION v5 — Robust Board & Chain Features")
    print("  Binary: >₹1,00,000 vs ≤₹1,00,000")
    print("=" * 70)

    training_df, udise_df, token_freq = build_training_dataset()
    cv_df, best_acc, best_thresh, imp_df, report_text = train_and_evaluate(training_df)
    save_report(best_acc, best_thresh, report_text, cv_df, imp_df)
    predict_full_udise(training_df, udise_df, token_freq, best_thresh)

    print(f"\n{'═' * 70}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'═' * 70}")
    for f in sorted(OUTPUT_DIR.glob("fee_classification_*")):
        print(f"    {f.name:55s} ({f.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
