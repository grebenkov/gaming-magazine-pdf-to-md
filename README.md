# Gaming Magazine PDF Processor (gmpdf)

A multi-stage OCR and content extraction pipeline for converting scanned gaming magazine PDFs into structured Markdown files.

## Overview

This tool processes gaming magazine scans through a 5-step pipeline:
1. **Extract** — Rasterize PDF pages to images (300 DPI) + extract embedded text layer
2. **OCR** — Run 3 OCR passes (DeepSeek-OCR, LightOnOCR, Tesseract)
3. **Merge** — Reconcile OCR outputs with local LLM (gemma3n)
4. **Structure** — Identify articles and categorize content using remote LLM (e.g., Gemini 2.5 Flash)
5. **Format** — Generate clean Markdown files organized by category

## Requirements

### System Dependencies
- Python 3.8+
- Tesseract OCR (`apt install tesseract-ocr` / `brew install tesseract`)
- Ollama with local models:
  - `deepseek-ocr` — Vision OCR model
  - `maternion/LightOnOCR-2` — Secondary OCR model
  - `gemma3n` — Text merging and formatting

### Python Packages
```bash
pip install PyMuPDF Pillow ollama openai pytesseract tqdm
```

### Hardware Requirements
- **GPU**: RTX 3080 with 12GB VRAM (minimum recommended)
- Local models (especially gemma3n) are memory-intensive and may struggle on weaker GPUs
- Step 5 can be particularly demanding on local hardware

### Remote API
For Step 4 (structure extraction), you need access to an OpenAI-compatible API:
- **Recommended**: Gemini 2.5 Flash or similar with large context window
- Step 5 optionally supports remote API execution (recommended for better quality)

## Installation

```bash
# Install system dependencies
# Ubuntu/Debian:
sudo apt install tesseract-ocr

# macOS:
brew install tesseract

# Install Python dependencies
pip install PyMuPDF Pillow ollama openai pytesseract tqdm

# Pull Ollama models
ollama pull deepseek-ocr
ollama pull maternion/LightOnOCR-2
ollama pull gemma3n
```

## Usage

### Basic Usage
```bash
python gmpdf.py magazine.pdf
```

### With Remote API (Bothub)
```bash
python gmpdf.py magazine.pdf \
  --openai-base-url https://bothub.chat/api/v2/openai/v1 \
  --openai-api-key YOUR_BOTHUB_API_KEY \
  --openai-model gemini-2.5-flash
```

### Resume from Specific Step
```bash
python gmpdf.py magazine.pdf --skip-to 4
```

### Use Remote Model for Step 5
```bash
python gmpdf.py magazine.pdf \
  --step5-use-remote \
  --openai-api-key YOUR_API_KEY \
  --openai-model gemini-2.5-flash
```

### Advanced Options
```bash
python gmpdf.py magazine.pdf \
  --output-dir ./processed \
  --work-dir ./temp \
  --dpi 300 \
  --magazine-name "GamePro Issue 42" \
  --step5-use-remote \
  --openai-api-key sk-... \
  --openai-model gemini-2.0-flash-exp
```

## Output Structure

```
output/
└── Magazine_Name/
    ├── game_reviews/
    │   ├── Final_Fantasy_VII.md
    │   └── Metal_Gear_Solid.md
    ├── game_previews/
    ├── hardware_and_software_reviews/
    ├── game_walkthroughs_and_guides/
    ├── stories_about_game_development/
    ├── news_and_industry_reports/
    ├── feature_articles/
    ├── ratings_and_sales_charts/
    └── bits_and_pieces/
```

Each Markdown file includes YAML front-matter:
```yaml
---
title: "Final Fantasy VII Review"
category: game_reviews
source_pages:
  - page_0042_corrected.txt
  - page_0043_corrected.txt
---
```

## Limitations

### 1. **Remove Advertisement Pages**
Pages with heavy advertising—especially those with dense catalogs and small text—should be removed from the PDF before processing. Ad-heavy pages can confuse the OCR models and produce poor results.

### 2. **Model Repetition Issues**
Some models may generate repetitive text on certain pages. If a particular output file is unusually large, it likely contains repeated content. The tool attempts to detect and truncate obvious cases, but not all repetition is caught.

### 3. **English Only**
Currently optimized for English-language magazines. Support for other languages is possible but would require different models than those currently used.

### 4. **Hardware Requirements**
Models are configured for RTX 3080 with 12GB VRAM, which appears to be the minimum viable configuration. The gemma3n model struggles particularly on Step 5 with less capable hardware.

### 5. **Remote API Recommended**
- **Step 4**: Requires remote API (e.g., Gemini 2.5 Flash) with large context window—no workarounds
- **Step 5**: Remote API optional but recommended for better output quality

## Pipeline Details

### Step 1: Extract
- Rasterizes PDF pages to PNG at specified DPI (default 300)
- Extracts embedded PDF text layer if available
- Output: `work/magazine/page_images/` and `work/magazine/pdf_text/`

### Step 2: OCR (3 Passes)
- **DeepSeek-OCR**: Vision-based OCR with grounding
- **LightOnOCR**: Specialized gaming magazine OCR
- **Tesseract**: Traditional OCR engine
- Output: `work/magazine/ocr_deepseek/`, `ocr_lightonocr/`, `ocr_tesseract/`

### Step 3: Merge & Correct
- Reconciles all OCR outputs using gemma3n
- Fixes errors, preserves structure, outputs clean text
- Output: `work/magazine/merged/page_XXXX_corrected.txt`

### Step 4: Structure Extraction
- Analyzes full magazine text with remote LLM
- Identifies articles, assigns categories, maps to pages
- Output: `work/magazine/structure.json`

### Step 5: Format Output
- Extracts individual articles from merged pages
- Formats as clean Markdown with YAML front-matter
- Organizes into category directories
- Output: `output/Magazine_Name/category/Article_Title.md`

## Environment Variables

```bash
export OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gemini-2.0-flash-exp"
```

## Troubleshooting

**Poor OCR quality**: Increase DPI (`--dpi 400`), remove advertisement pages, ensure good scan quality

**JSON parse errors in Step 4**: Check `work/magazine/structure_raw.json` for API response issues

## Example (directory list)

[PC Zone 29](https://archive.org/details/PCZONE029/mode/2up)

```text
PC.Zone.29.August.1995/
├── + INTERNAL_DOCS/
├── + bits_and_pieces/
│   ├── - Command_&_Conquer_(Correction).md
│   ├── - Culky_Corner_(Reader_Letters).md
│   ├── - Culky_Goes_To_EA_(Cover_Disk_Video).md
│   ├── - Dark_Forces_(Cover_Disk_Demo).md
│   ├── - Darker_(Cover_Disk_Demo).md
│   ├── - Discworld_Sorted_(Reader_Letter).md
│   ├── - Dr_Drago’s_Madcap_Chase_(Cover_Disk_Demo).md
│   ├── - Find_Loads_of_Dosh_(Riddle_of_the_Rune_Screensaver_Competition).md
│   ├── - First_Encounters..._Continued_(Reader_Letters).md
│   ├── - Hell_In_A_Handbasket..._(Reader_Letter).md
│   ├── - Help_Me!_I'm_Frowning..._(Troubleshooting_Guide).md
│   ├── - Hi-Octane_(Cover_Disk_Demo).md
│   ├── - Keep_On_Drummin'_(Competition).md
│   ├── - Lemmings_3D_(Cover_Disk_Demo).md
│   ├── - Level_Editors_&_Trainers_(Cover_Disk).md
│   ├── - Micro_Machines_2_(Cover_Disk_Demo).md
│   ├── - Panzer_General_(Cover_Disk_Demo).md
│   ├── - Pinball_Mania_(Cover_Disk_Demo).md
│   ├── - Politically_Correct_(Reader_Letter).md
│   ├── - Primal_Rage_(Cover_Disk_Demo).md
│   ├── - Rampant_Man_Hater_(Reader_Letter).md
│   ├── - Rebel_Assault_2_(Cover_Disk_Preview).md
│   ├── - SirDoom_(Cover_Disk).md
│   ├── - Space_Quest_VI_(Cover_Disk_Demo).md
│   ├── - Star_Trek_The_Truth_(Reader_Letter).md
│   ├── - Star_Wars_Special_(Cover_Disk_Demos).md
│   ├── - Super_Streetfighter_II_Turbo_(Cover_Disk_Demo).md
│   ├── - TIE_Fighter_(Cover_Disk_Demo).md
│   ├── - The_Complete_Descent_Level_Editor_(Cover_Disk).md
│   ├── - The_Scroll_(Cover_Disk_Demo).md
│   ├── - Toilets_In_Doom_(Reader_Letters).md
│   ├── - Weird_And_French_(Reader_Letter).md
│   ├── - Windows_'95_(Cover_Disk_Demo).md
│   └── - X-Wing_(Cover_Disk_Demo).md
├── + feature_articles/
│   ├── - Art_Watch_(Pro_Celebrity_Deathmatches).md
│   └── - John's_bit_on_the_side..._(Editor's_Column).md
├── + game_previews/
│   ├── - '96_-_The_Year_of_Sport_(EA_Sports_Titles).md
│   ├── - Actua_Soccer.md
│   ├── - Agile_Warrior_F-111X.md
│   ├── - Air_Power.md
│   ├── - Alien_Alliance.md
│   ├── - Battle_Beast.md
│   ├── - Championship_Manager_2.md
│   ├── - Crusader_No_Remorse.md
│   ├── - Flashback_2_(Fade_To_Black).md
│   ├── - Gabriel_Knight_2.md
│   ├── - IndyCar_Racing_2.md
│   ├── - LucasArts_Doomed_Again_(Calia_2095).md
│   ├── - Magic_Carpet_2.md
│   ├── - MechWarrior_2.md
│   ├── - Motorcross.md
│   ├── - Outpost_Pinball.md
│   ├── - ParaSite.md
│   ├── - PowerSports_Soccer.md
│   ├── - Primal_Rage.md
│   ├── - Psychic_Detective.md
│   ├── - Rise_of_the_Robots_2.md
│   ├── - SU27_Flanker.md
│   ├── - Scrreamer.md
│   ├── - Sonic_now_PC.md
│   ├── - TFX_EF2000.md
│   ├── - The_Need_For_Speed.md
│   ├── - To_Boldly_Go_(Again)_(Tekwar).md
│   ├── - Toonstruck.md
│   ├── - UAKM_2_(The_Pandora_Device).md
│   ├── - US_Navy_Fighters_Add-On.md
│   ├── - Urban_Decay.md
│   └── - Wavelength.md
├── + game_reviews/
│   ├── - Civil_War.md
│   ├── - FX_Fighters.md
│   ├── - Hi-Octane.md
│   ├── - Micro_Machines_2.md
│   ├── - Orion_Conspiracy.md
│   ├── - Perfect_General_2.md
│   ├── - Picture_Perfect_Golf.md
│   ├── - Prisoner_of_Ice.md
│   ├── - Scottish_Open_Golf.md
│   ├── - Silverload.md
│   ├── - Striker_95.md
│   ├── - Ultimate_Doom.md
│   └── - Vortex.md
├── + game_walkthroughs_and_guides/
│   └── - Full_Throttle.md
├── + hardware_and_software_reviews/
│   ├── - Ace_MovieMaster_Classic.md
│   ├── - AeroPoint_AeroDuet.md
│   ├── - Bravo_for_Primax_(Soundcards).md
│   ├── - Easy_For_Two_To_Play_(Alfa_Twin_Duo_Joystick_Adaptor).md
│   ├── - Evolution_ev90_Dynamite.md
│   ├── - Graphics_Card_Group_Test.md
│   └── - Sony_SRS_PC50_Speakers.md
├── + news_and_industry_reports/
│   ├── - Beeb_Portfolio_HL_(Accolade_Survey).md
│   ├── - Blade_Runner_Rights_Sold.md
│   ├── - Dark_Forces_(Custom_Missions_&_DFUSE).md
│   ├── - Descent_(DTX_&_DEVIL_Level_Editor).md
│   ├── - Descent_Level_Competition.md
│   ├── - Doom_(Level_Editors_&_DOOM-IT).md
│   ├── - Doom_Tournaments.md
│   ├── - Easy-buy_Compaqs.md
│   ├── - Heretic_(Deathmatch_Levels_&_BOOM_HEEP).md
│   ├── - Internet_First_(MJN_Online_PC_Sales).md
│   ├── - Interplay_Gallup_(Games_Domain).md
│   ├── - MacDoom.md
│   ├── - On-Line_Footie_(Interactive_Football_League).md
│   ├── - Rise_of_the_Triad_(ROTTED_Level_Editor).md
│   ├── - TSR_go_with_Interplay.md
│   ├── - Update_Watch_(Game_Patches).md
│   └── - X-Wing_(Mini-fighter_Builder_&_Ship_Editor).md
├── + ratings_and_sales_charts/
│   └── - Gallup_Charts_(Top_20_Full_Price,_Top_10_PC_Budget,_Top_10_CD-ROM).md
└── + stories_about_game_development/
    ├── - At_Home_With..._Apogee!_(3D_Realms_Entertainment).md
    └── - Rebel_Assault_2.md
```

## License

MIT

## Contributing

Issues and pull requests welcome at the project repository.
