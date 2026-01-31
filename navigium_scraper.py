"""
Navigium.de Scraper Module
Extracts Latin word information (lemma, grammar, translation) from navigium.de
"""

import requests
from bs4 import BeautifulSoup
import re
import json
import os
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

BASE_URL = "https://www.navigium.de/latein-woerterbuch"

# Globale Session für Connection Pooling
scraper_session = requests.Session()
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=100)
scraper_session.mount("http://", adapter)
scraper_session.mount("https://", adapter)

# Cache-Datei für persistentes Caching
CACHE_FILE = os.path.join(os.path.dirname(__file__), '.word_cache.json')

# In-Memory Cache (wird beim Start aus Datei geladen)
word_cache = {}

def load_cache():
    """Lädt den Cache aus der JSON-Datei."""
    global word_cache
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                word_cache = json.load(f)
    except (json.JSONDecodeError, IOError):
        word_cache = {}

def save_cache():
    """Speichert den Cache in die JSON-Datei."""
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(word_cache, f, ensure_ascii=False, indent=2)
    except IOError:
        pass

# Cache beim Modulstart laden
load_cache()


def clean_text(text: str) -> str:
    """Bereinigt Text von überflüssigen Leerzeichen und Zeilenumbrüchen."""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()


def preprocess_text(text: str) -> str:
    """
    Bereitet Text für die Analyse vor:
    - Entfernt seltsame Unicode-Zeichen
    - Normalisiert Leerzeichen
    - Behält nur lateinische Buchstaben und Standardzeichen
    """
    if not text:
        return ""
    
    # Ersetze häufige Unicode-Varianten
    replacements = {
        '\u2018': "'", '\u2019': "'",  # Curly quotes
        '\u201c': '"', '\u201d': '"',
        '\u2014': '-', '\u2013': '-',  # Dashes
        '\u00a0': ' ',  # Non-breaking space
        '\u2026': '...',  # Ellipsis
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Entferne alle nicht-druckbaren Zeichen
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
    
    # Normalisiere Leerzeichen
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def fetch_page(url: str) -> BeautifulSoup:
    """Holt eine Seite und gibt ein BeautifulSoup-Objekt zurück."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    response = scraper_session.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return BeautifulSoup(response.text, 'lxml')


def parse_result_container(container, word: str, nr: int) -> dict:
    """
    Parst einen einzelnen Ergebnis-Container (div.umgebend).
    Validiert auch, ob das gesuchte Wort tatsächlich als Form des Lemmas vorkommt.
    
    WICHTIG: Nur das unterstrichene Wort (u-Tag) gilt als echte Form.
    Andere Erwähnungen (z.B. in Beispielsätzen) werden ignoriert.
    """
    result = {
        'word_form': word,
        'nr': nr,
        'lemma': None,
        'grammar': None,
        'translation': None,
        'found': False,
        'word_matches': False  # True nur wenn u-Tag exakt übereinstimmt
    }
    
    inner = container.find('div', class_='innen')
    if not inner:
        return result
    
    # Lemma extrahieren aus div.lemma > span
    lemma_div = inner.find('div', class_='lemma')
    if lemma_div:
        lemma_span = lemma_div.find('span')
        if lemma_span:
            result['lemma'] = clean_text(lemma_span.get_text())
            result['found'] = True
        # Auch die Wortart hinzufügen, falls vorhanden
        wortart = lemma_div.find('i', class_='wortart')
        if wortart and result['lemma']:
            result['lemma'] += ' ' + clean_text(wortart.get_text())
    
    # Grammatik extrahieren - suche nach dem div mit dem unterstrichenen Wort
    # Das u-Tag enthält die EXAKTE Wortform die zu diesem Lemma gehört
    word_lower = word.lower()
    
    for div in inner.find_all('div'):
        u_tag = div.find('u')
        if u_tag:
            # Das unterstrichene Wort ist DIE Form die zu diesem Lemma gehört
            underlined_word = clean_text(u_tag.get_text()).lower()
            
            # NUR wenn das unterstrichene Wort EXAKT dem Suchwort entspricht
            # wird dieser Eintrag als gültige Form betrachtet
            if underlined_word == word_lower:
                result['word_matches'] = True
            
            # Das Format ist normalerweise: "word: Grammar Info"
            text = clean_text(div.get_text())
            if ':' in text:
                grammar_part = text.split(':', 1)[1].strip()
                result['grammar'] = grammar_part
            break
    
    # KEIN Fallback mehr! Nur exakte u-Tag Übereinstimmung zählt.
    # Einträge in Beispielsätzen werden so korrekt ausgeschlossen.
    
    # Übersetzungen extrahieren aus ol > li > .bedeutung
    ol = inner.find('ol')
    if ol:
        meanings = []
        for li in ol.find_all('li')[:5]:  # Maximal 5 Bedeutungen
            bedeutung = li.find(class_='bedeutung')
            if bedeutung:
                text = clean_text(bedeutung.get_text())
                if text:
                    meanings.append(text)
        if meanings:
            result['translation'] = '; '.join(meanings)
    
    # Falls keine strukturierten Bedeutungen, versuche einfachen Text-Extrakt
    if not result['translation']:
        text = clean_text(inner.get_text())
        # Suche nach typischen Übersetzungsmustern
        lines = text.split('\n')
        for line in lines:
            if ',' in line and len(line) < 150:
                # Könnte eine Übersetzungsliste sein
                result['translation'] = clean_text(line)
                break
    
    return result


def lookup_word(word: str, nr: int = 1) -> dict:
    """
    Schlägt ein lateinisches Wort auf navigium.de nach.
    
    Args:
        word: Das zu suchende lateinische Wort
        nr: Die Ergebnisnummer (für Wörter mit mehreren Bedeutungen)
    
    Returns:
        Dictionary mit lemma, grammar, translation, word_form
    """
    cache_key = f"{word.lower()}_{nr}"
    if cache_key in word_cache:
        return word_cache[cache_key]
    
    url = f"{BASE_URL}/{word}?wb=gross&nr={nr}"
    
    try:
        soup = fetch_page(url)
        
        # Suche nach allen Ergebnis-Containern
        containers = soup.find_all('div', class_='umgebend')
        
        if containers:
            # Bei nr-Parameter: Wenn mehrere vorhanden, zeige die entsprechende
            index = min(nr - 1, len(containers) - 1)
            result = parse_result_container(containers[index], word, nr)
            result['url'] = url
            
            # Sammle Alternativen (andere mögliche Lemmata)
            if len(containers) > 1:
                result['alternatives'] = []
                for i, cont in enumerate(containers):
                    if i != index:
                        alt_result = parse_result_container(cont, word, i + 1)
                        if alt_result['found']:
                            result['alternatives'].append({
                                'nr': i + 1,
                                'lemma': alt_result['lemma']
                            })
            else:
                result['alternatives'] = []
                
        else:
            # Fallback: Versuche alte Extraktion
            result = {
                'word_form': word,
                'nr': nr,
                'lemma': None,
                'grammar': None,
                'translation': None,
                'alternatives': [],
                'found': False,
                'url': url
            }
            
            # Suche in der gesamten Seite nach Informationen
            result_text = soup.get_text()
            
            # Grammatik-Pattern
            grammar_patterns = [
                r'(\d+\.\s*Pers\.\s*(?:Sg|Pl)\.\s*(?:Präs|Perf|Imperf|Plusq|Fut)\.\s*(?:Ind|Konj|Imp)\.\s*(?:Akt|Pass)\.?)',
                r'((?:Nom|Gen|Dat|Akk|Abl|Vok)\.\s*(?:Sg|Pl)\.?)',
                r'(Inf\.\s*(?:Präs|Perf|Fut)\.\s*(?:Akt|Pass)\.?)'
            ]
            for pattern in grammar_patterns:
                match = re.search(pattern, result_text)
                if match:
                    result['grammar'] = match.group(1)
                    result['found'] = True
                    break
        
        word_cache[cache_key] = result
        return result
        
    except requests.RequestException as e:
        return {
            'word_form': word,
            'nr': nr,
            'lemma': None,
            'grammar': None,
            'translation': None,
            'alternatives': [],
            'found': False,
            'error': str(e),
            'url': f"{BASE_URL}/{word}?wb=gross&nr={nr}"
        }


def lookup_word_all_meanings(word: str) -> List[dict]:
    """
    Schlägt ein lateinisches Wort nach und holt ALLE möglichen Bedeutungen.
    
    WICHTIG: Extrahiert NUR Container aus dem "Formen"-Bereich, 
    NICHT aus dem "Phrasen und Redewendungen"-Bereich.
    
    Args:
        word: Das zu suchende lateinische Wort
    
    Returns:
        Liste aller möglichen Bedeutungen des Wortes (nur echte Formen)
        Leere Liste wenn keine Formen gefunden wurden
    """
    url = f"{BASE_URL}/{word}?wb=gross"
    
    # Cache-Check
    cache_key = f"all_{word}"
    if cache_key in word_cache:
        return word_cache[cache_key]
    
    try:
        soup = fetch_page(url)
        
        # Finde alle h3-Überschriften mit Klasse "ergebnis"
        # Diese trennen die Bereiche "lat. Formen" vs "Phrasen und Redewendungen"
        h3_headers = soup.find_all('h3', class_='ergebnis')
        
        # Sammle nur Container die zum "Formen"-Bereich gehören
        forms_containers = []
        
        for h3 in h3_headers:
            header_text = clean_text(h3.get_text())
            
            # Nur den "lat. Formen" Bereich verarbeiten
            if 'lat. Formen' in header_text:
                # Alle nachfolgenden Geschwister-Elemente durchgehen
                # bis zum nächsten h3 oder Ende
                sibling = h3.next_sibling
                while sibling:
                    # Prüfen ob es ein Element ist (nicht nur Text)
                    if hasattr(sibling, 'name'):
                        # Stoppen wenn wir einen neuen h3 Header erreichen
                        if sibling.name == 'h3':
                            break
                        # Container mit Klasse "umgebend" sammeln
                        if sibling.name == 'div' and 'umgebend' in sibling.get('class', []):
                            forms_containers.append(sibling)
                    sibling = sibling.next_sibling
        
        if not forms_containers:
            # Keine Formen gefunden - leere Liste cachen und zurückgeben
            word_cache[cache_key] = []
            return []
        
        # Container parsen
        all_results = []
        for i, container in enumerate(forms_containers):
            result = parse_result_container(container, word, i + 1)
            result['url'] = f"{BASE_URL}/{word}?wb=gross&nr={i+1}"
            result['alternatives'] = []
            
            # Ergebnis hinzufügen wenn es gefunden wurde
            if result['found']:
                all_results.append(result)
        
        # Cache speichern
        word_cache[cache_key] = all_results
        return all_results
        
    except requests.RequestException:
        return []


def analyze_text(text: str, fetch_all_meanings: bool = True) -> list:
    """
    Analysiert einen lateinischen Text Wort für Wort.
    Verwendet parallele Abfragen für maximale Geschwindigkeit.
    
    Args:
        text: Der zu analysierende lateinische Text
        fetch_all_meanings: Ob alle Bedeutungen für ambigue Wörter geholt werden sollen
    
    Returns:
        Liste von Wörterbucheinträgen für jedes Wort (nur Wörter mit Ergebnissen)
    """
    text = preprocess_text(text)
    words = re.findall(r'[a-zA-ZäöüÄÖÜāēīōūĀĒĪŌŪ]+', text.lower())
    
    # Deduplizieren und filtern
    unique_words = []
    seen = set()
    for word in words:
        if word not in seen and len(word) >= 2:
            seen.add(word)
            unique_words.append(word)
    
    # Parallele Abfragen mit ThreadPoolExecutor
    results_dict = {}
    
    def lookup_word_wrapper(word):
        if fetch_all_meanings:
            return word, lookup_word_all_meanings(word)
        else:
            result = lookup_word(word)
            return word, [result] if result.get('found') else []
    
    # Maximale Parallelität - so viele Threads wie Wörter (bis zu 50)
    max_workers = min(len(unique_words), 50)
    
    if max_workers > 0:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(lookup_word_wrapper, word): word for word in unique_words}
            
            for future in as_completed(futures):
                try:
                    word, word_results = future.result()
                    if word_results:
                        results_dict[word] = word_results
                except Exception:
                    pass
    
    # Cache periodisch speichern
    save_cache()
    
    # Ergebnisse in der ursprünglichen Reihenfolge zurückgeben
    results = []
    for word in unique_words:
        if word in results_dict:
            results.append({
                'word': word,
                'meanings': results_dict[word],
                'has_multiple': len(results_dict[word]) > 1
            })
    
    return results


if __name__ == "__main__":
    # Test mit ambiguen Wörtern
    test_words = ["cecidi", "amavit", "puellam", "est"]
    for word in test_words:
        print(f"\n=== {word} ===")
        results = lookup_word_all_meanings(word)
        for i, result in enumerate(results, 1):
            print(f"\n  Bedeutung {i}:")
            print(f"    Lemma: {result['lemma']}")
            print(f"    Grammar: {result['grammar']}")
            print(f"    Translation: {result['translation']}")
            print(f"    Found: {result['found']}")
