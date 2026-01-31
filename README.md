# Verbum

**Lateinischer Text-Analysator** – Analysiere lateinische Texte und finde Grundformen, Übersetzungen & Grammatik.

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Features

- 📖 **Wortanalyse** – Automatische Erkennung von Grundformen (Lemmata), grammatischen Informationen und Übersetzungen
- 🔍 **Mehrdeutige Wörter** – Zeigt alle möglichen Bedeutungen für ambigue Formen (z.B. *cecidi*)
- 📊 **Wortfrequenz-Diagramm** – Visualisiere die Verteilung bestimmter Wörter im Text
- 🎯 **Interaktive Navigation** – Klicke auf das Diagramm, um zur entsprechenden Textstelle zu springen
- ⚡ **Caching** – Schnelle Wiederholungsanalysen durch intelligentes Caching

## Installation

### Voraussetzungen

- Python 3.8 oder höher
- pip

### Setup

```bash
# Repository klonen
git clone https://github.com/lukas-hzb/verbum.git
cd verbum

# Virtuelle Umgebung erstellen
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# oder: .venv\Scripts\activate  # Windows

# Abhängigkeiten installieren
pip install -r requirements.txt

# Server starten
python app.py
```

Die App läuft unter: **http://localhost:5000**

## Verwendung

1. Gib einen lateinischen Text in das linke Textfeld ein
2. Klicke auf **"Text analysieren"**
3. Die Analyse erscheint rechts mit Grundformen und Übersetzungen
4. Wechsle zum Tab **"Wortfrequenz"** um die Verteilung bestimmter Wörter zu visualisieren

## Technologie

- **Backend**: Flask (Python)
- **Frontend**: Vanilla HTML/CSS/JavaScript
- **Diagramme**: Chart.js
- **Datenquelle**: navigium.de

## Lizenz

MIT License – siehe [LICENSE](LICENSE)
