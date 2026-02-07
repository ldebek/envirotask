# Streams Point Numerator - Numerator Punktów dla QGIS

Skrypt do automatycznej numeracji punktów na ciekach wodnych w środowisku QGIS.

## Opis

`streams_point_numerator.py` to narzędzie umożliwiające automatyczne numerowanie punktów zlokalizowanych wzdłuż cieków wodnych. Skrypt przypisuje punkty do odpowiednich cieków na podstawie ich położenia przestrzennego, a następnie nadaje im numery zgodnie z logiką uwzględniającą istniejące (stare) numery.

## Wymagania

- **QGIS** (wersja 3.x - testowane na QGIS 3.40)
- **Python** 3.6+

## Struktura Danych

### Wymagane warstwy

Skrypt wymaga dwóch warstw wektorowych załadowanych w projekcie QGIS:

1. **Warstwa cieków** (nazwa: `cieki`)
   - Typ geometrii: LineString lub MultiLineString
   - Wymagane pole: `oznaczenie` - identyfikator cieku

2. **Warstwa punktów** (nazwa: `punkty`)
   - Typ geometrii: Point
   - Wymagane pola:
     - `numer-stary` - pole zawierające istniejące numery punktów (może być puste)
     - `numer-nowy` - pole, do którego zostaną zapisane nowe numery (może być puste przed uruchomieniem)

## Algorytm Numeracji

Skrypt działa według następującego algorytmu:

### 1. Łączenie geometrii cieków
- Cieki o tym samym `oznaczeniu` są łączone w jeden obiekt geometryczny
- Weryfikacja i korekta kierunku przepływu cieku

### 2. Przypisywanie punktów do cieków
- Punkty są przypisywane do cieków na podstawie ich położenia przestrzennego
- Wykorzystywany jest indeks przestrzenny dla optymalizacji wydajności
- Punkty są sortowane według odległości od początku cieku

### 3. Numeracja punktów

Logika numeracji zależy od obecności starych numerów:

#### Przypadek 1: Brak starych numerów na cieku
Wszystkie punkty numerowane są sekwencyjnie: `1P`, `2P`, `3P`, ...

#### Przypadek 2: Obecne są stare numery

Punkty są numerowane w trzech sekcjach:

**a) Punkty PRZED pierwszym punktem ze starym numerem:**
- Format: `1Pnowy`, `2Pnowy`, `3Pnowy`, ...

**b) Punkty MIĘDZY punktami ze starymi numerami:**
- Stare numery są przepisywane bez zmian
- Nowe punkty otrzymują sufiks literowy
- Format: `5Pa`, `5Pb`, `5Pc`, ... (gdzie 5 to numer poprzedniego punktu)
- Przykład: między punktami `5P` i `6P` dodawane punkty to `5Pa`, `5Pb`, itd.

**c) Punkty PO ostatnim punkcie ze starym numerem:**
- Kontynuacja numeracji od ostatniego starego numeru
- Format: `6P`, `7P`, `8P`, ...

### 4. Aktualizacja warstwy
- Nowe numery są zapisywane w polu `numer-nowy`
- Punkty niepowiązane z żadnym ciekiem otrzymują wartość NULL

## Użycie

### Uruchomienie z konsoli QGIS

1. Otwórz projekt QGIS z załadowanymi warstwami `cieki` i `punkty`
2. Otwórz konsolę Pythona w QGIS (Wtyczki → Konsola Pythona)
3. Otwórz skrypt `streams_point_numerator.py` i uruchom go.
