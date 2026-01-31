"""
Latin Text Analyzer - Flask Application
Analyzes Latin texts by looking up words on navigium.de
"""

from flask import Flask, render_template, request, jsonify
from navigium_scraper import lookup_word, analyze_text, preprocess_text, lookup_word_all_meanings
import hashlib

app = Flask(__name__)

# Serverseitiger Cache für die letzte(n) Analyse(n)
# Key: SHA256 Hash des Textes
# Value: Analyse-Ergebnisse (dict)
ANALYSIS_CACHE = {}

def get_text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


@app.route('/')
def index():
    """Hauptseite mit Zwei-Panel-Layout."""
    return render_template('index.html')


@app.route('/api/lookup/<word>')
def api_lookup(word: str):
    """
    API-Endpoint für Einzelwort-Suche.
    
    Query-Parameter:
        nr: Ergebnisnummer für ambigue Wörter (default: 1)
    """
    nr = request.args.get('nr', 1, type=int)
    result = lookup_word(word, nr)
    return jsonify(result)


@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    """
    API-Endpoint für Textanalyse.
    
    Request Body (JSON):
        text: Der zu analysierende lateinische Text
    """
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({'error': 'Kein Text angegeben'}), 400
    
    text = preprocess_text(data['text'])
    if not text.strip():
        return jsonify({'error': 'Text ist leer'}), 400
    
    text_hash = get_text_hash(text)
    if text_hash in ANALYSIS_CACHE:
        results = ANALYSIS_CACHE[text_hash]
    else:
        results = analyze_text(text)
        ANALYSIS_CACHE[text_hash] = results
    
    return jsonify({
        'original_text': text,
        'word_count': len(results),
        'results': results
    })


@app.route('/api/word-frequency', methods=['POST'])
def api_word_frequency():
    """
    API-Endpoint für Wortfrequenz-Analyse.
    Führt Suchwörter auf Grundformen zurück und sucht dann im Text nach allen
    Wörtern, die auf dieselben Grundformen zurückführen.
    
    Request Body (JSON):
        text: Der zu durchsuchende Text
        search_words: Liste von Suchwörtern
    """
    import re
    from navigium_scraper import lookup_word_all_meanings, preprocess_text
    
    data = request.get_json()
    if not data or 'text' not in data or 'search_words' not in data:
        return jsonify({'error': 'Text und Suchwörter erforderlich'}), 400
    
    text = preprocess_text(data['text'])
    search_words = data['search_words']
    text_hash = get_text_hash(text)
    
    # Prüfe ob wir Analyse-Ergebnisse für diesen Text haben
    cached_analysis = ANALYSIS_CACHE.get(text_hash)
    
    # Hilfsfunktion: Diakritische Zeichen entfernen
    def normalize(s):
        import re
        return re.sub(r'[āēīōūĀĒĪŌŪ]', 
            lambda m: {'ā':'a','ē':'e','ī':'i','ō':'o','ū':'u',
                       'Ā':'A','Ē':'E','Ī':'I','Ō':'O','Ū':'U'}[m.group()], 
            s.lower())
    
    # Hilfsfunktion: Lemmas für ein Wort ermitteln
    def get_lemmas(word):
        # Falls wir Ergebnisse aus der Vollanalyse haben, nutze diese!
        if cached_analysis:
            for item in cached_analysis:
                if item['word'] == word:
                    lemmas = set()
                    for m in item.get('meanings', []):
                        if m.get('lemma'):
                            lemmas.add(normalize(m['lemma'].split()[0]))
                    lemmas.add(normalize(word))
                    return lemmas

        lemmas = set()
        meanings = lookup_word_all_meanings(word.lower())
        for meaning in meanings:
            if meaning.get('lemma'):
                # Extrahiere erstes Wort aus dem Lemma (z.B. "arma -ōrum" -> "arma")
                lemma_first = meaning['lemma'].split()[0]
                lemmas.add(normalize(lemma_first))
        # Auch das Wort selbst hinzufügen
        lemmas.add(normalize(word))
        return lemmas
    
    # Text in Wörter aufteilen
    import re
    words_in_text = re.findall(r'[a-zA-ZäöüÄÖÜāēīōūĀĒĪŌŪ]+', text.lower())
    total_words = len(words_in_text)
    
    # Cache für Wort-Lemmas (verwende Vollanalyse falls vorhanden)
    text_word_lemmas_cache = {}
    if cached_analysis:
        for item in cached_analysis:
            w = item['word']
            ls = set()
            for m in item.get('meanings', []):
                if m.get('lemma'):
                    ls.add(normalize(m['lemma'].split()[0]))
            ls.add(normalize(w))
            text_word_lemmas_cache[w] = ls
    
    # Für jedes Suchwort: Grundformen finden und Positionen ermitteln
    word_data = []
    
    for search_word in search_words:
        # Grundform(en) des Suchworts finden
        search_lemmas = get_lemmas(search_word)
        
        # Positionen finden wo ein Textwort dieselbe Grundform hat
        positions = []
        for i, text_word in enumerate(words_in_text):
            # Lemmas für dieses Textwort ermitteln (mit Cache)
            if text_word not in text_word_lemmas_cache:
                text_word_lemmas_cache[text_word] = get_lemmas(text_word)
            
            text_lemmas = text_word_lemmas_cache[text_word]
            
            # Prüfen ob es eine Überschneidung gibt
            if search_lemmas & text_lemmas:  # Schnittmenge
                positions.append(i + 1)  # 1-basierte Position
        
        word_data.append({
            'search_word': search_word,
            'lemmas': list(search_lemmas),
            'positions': positions,
            'count': len(positions)
        })
    
    return jsonify({
        'total_words': total_words,
        'word_data': word_data
    })


if __name__ == '__main__':
    import subprocess
    import os
    import time
    
    PORT = 5000
    
    # Nur beim Hauptprozess Port freigeben (nicht beim Reloader-Kindprozess)
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        try:
            # Finde und beende Prozesse die den Port nutzen
            result = subprocess.run(
                f"lsof -ti :{PORT}",
                shell=True,
                capture_output=True,
                text=True
            )
            pids = [p.strip() for p in result.stdout.strip().split('\n') if p.strip()]
            
            if pids:
                for pid in pids:
                    try:
                        os.kill(int(pid), 9)
                        print(f"Prozess {pid} auf Port {PORT} beendet")
                    except (ProcessLookupError, ValueError):
                        pass
                time.sleep(0.5)
        except Exception:
            pass
        
        print(f"Lateinischer Text-Analysator: http://localhost:{PORT}")
    
    app.run(debug=True, port=PORT, host='0.0.0.0')
