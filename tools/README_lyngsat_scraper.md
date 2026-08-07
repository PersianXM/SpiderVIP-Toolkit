# LyngSat Frequency Scraper

Extracts transponder data (`Frequency`, `Polarization`, `SR`, `FEC`) from a
LyngSat satellite page and saves it to a `.txt` file (tab separated).

## Requirements

```
pip install requests beautifulsoup4
```

## Usage

Interactive (prompts for the URL):

```
python tools/lyngsat_scraper.py
```

Pass the URL directly and choose an output file:

```
python tools/lyngsat_scraper.py "https://www.lyngsat.com/Turksat-3A-4A-5B-6A.html" -o frequencies.txt
```

## Output format

```
10954 H	3333	3/4
10960 V	4100	5/6
10965 H	5000	5/6
```

Columns are: `Frequency Polarization` <TAB> `SR` <TAB> `FEC`.

## Filtering rules

1. **Encryption** – if a transponder's channels are all encrypted
   (Irdeto, Nagravision, Conax, Viaccess, BISS, PowerVu, etc.), that
   frequency is **skipped**. A transponder is kept if it has at least one
   free-to-air channel.
2. **Feeds** – channels whose *Provider Name* is a feed (contains "feed")
   are ignored. If a transponder only has feed entries, it is **skipped**.

## Offline test

`test_lyngsat_parse.py` validates the parsing/filtering logic against a
synthetic LyngSat-style table (useful when direct network access to
lyngsat.com is unavailable):

```
python tools/test_lyngsat_parse.py
```
