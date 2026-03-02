# Обработчик игровых журналов в PDF (gmpdf)

Многоступенчатый конвейер OCR и извлечения контента для преобразования отсканированных игровых журналов в структурированные Markdown-файлы.

## Описание

Инструмент обрабатывает сканы игровых журналов через 5-этапный конвейер:
1. **Извлечение** — Растеризация страниц PDF в изображения (300 DPI) + извлечение встроенного текстового слоя
2. **OCR** — Три прохода распознавания текста (DeepSeek-OCR, LightOnOCR, Tesseract)
3. **Объединение** — Сведение результатов OCR с помощью локальной LLM (gemma3n)
4. **Структурирование** — Идентификация статей и категоризация контента с помощью удалённой LLM (например, Gemini 2.5 Flash)
5. **Форматирование** — Генерация чистых Markdown-файлов, организованных по категориям

## Требования

### Системные зависимости
- Python 3.8+
- Tesseract OCR (`apt install tesseract-ocr` / `brew install tesseract`)
- Ollama с локальными моделями:
  - `deepseek-ocr` — Модель OCR с компьютерным зрением
  - `maternion/LightOnOCR-2` — Вторичная модель OCR
  - `gemma3n` — Объединение текста и форматирование

### Python-пакеты
```bash
pip install PyMuPDF Pillow ollama openai pytesseract tqdm
```

### Требования к оборудованию
- **GPU**: RTX 3080 с 12 ГБ видеопамяти (минимально рекомендуемая)
- Локальные модели (особенно gemma3n) требовательны к памяти и могут не справляться на более слабых GPU
- Шаг 5 может быть особенно требовательным к локальному оборудованию

### Удалённый API
Для Шага 4 (извлечение структуры) требуется доступ к OpenAI-совместимому API:
- **Рекомендуется**: Gemini 2.5 Flash или аналог с большим контекстным окном
- Шаг 5 опционально поддерживает выполнение через удалённый API (рекомендуется для лучшего качества)

## Установка

```bash
# Установка системных зависимостей
# Ubuntu/Debian:
sudo apt install tesseract-ocr

# macOS:
brew install tesseract

# Установка Python-зависимостей
pip install PyMuPDF Pillow ollama openai pytesseract tqdm

# Загрузка моделей Ollama
ollama pull deepseek-ocr
ollama pull maternion/LightOnOCR-2
ollama pull gemma3n
```

## Использование

### Базовое использование
```bash
python gmpdf.py magazine.pdf
```

### С удалённым API (Gemini)
```bash
python gmpdf.py magazine.pdf \
  --openai-base-url https://generativelanguage.googleapis.com/v1beta/openai/ \
  --openai-api-key ВАШ_GEMINI_API_KEY \
  --openai-model gemini-2.0-flash-exp
```

### Продолжение с определённого шага
```bash
python gmpdf.py magazine.pdf --skip-to 4
```

### Использование удалённой модели для Шага 5
```bash
python gmpdf.py magazine.pdf \
  --step5-use-remote \
  --openai-api-key ВАШ_API_KEY \
  --openai-model gemini-2.0-flash-exp
```

### Расширенные опции
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

## Структура выходных данных

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

Каждый Markdown-файл включает YAML-метаданные:
```yaml
---
title: "Final Fantasy VII Review"
category: game_reviews
source_pages:
  - page_0042_corrected.txt
  - page_0043_corrected.txt
---
```

## Ограничения

### 1. **Страницы с рекламой лучше удалять**
Страницы с большим количеством рекламы — особенно те, на которых много мелкого текста (различные каталоги) — следует удалить из PDF перед обработкой. Страницы с большим количеством рекламы могут запутать модели OCR и дать плохие результаты.

### 2. **Проблемы с повторениями в моделях**
У моделей может «срывать крышу» на некоторых страницах — если какой-то файл явно выделяется по объёму, значит, скорее всего, туда нагнало повторов. Самые откровенные случаи ловятся и урезаются автоматически, но не всё и не всегда.

### 3. **Только английский язык**
В настоящее время оптимизировано для журналов на английском языке. Можно доработать для поддержки других языков, но не с текущими используемыми моделями — они не тянут.

### 4. **Требования к оборудованию**
Модели подобраны под RTX 3080 с 12 гигабайтами памяти. И это, судя по всему, минимальный минимум. Модель gemma3n еле справляется, особенно на Шаге 5.

### 5. **Рекомендуется удалённый API**
- **Шаг 4**: Требуется удалённый API (например, Gemini 2.5 Flash) с большим контекстным окном — без вариантов
- **Шаг 5**: Удалённый API опционален, но желателен для лучшего качества вывода

## Детали конвейера

### Шаг 1: Извлечение
- Растеризация страниц PDF в PNG с указанным DPI (по умолчанию 300)
- Извлечение встроенного текстового слоя PDF, если доступен
- Результат: `work/magazine/page_images/` и `work/magazine/pdf_text/`

### Шаг 2: OCR (3 прохода)
- **DeepSeek-OCR**: OCR на основе компьютерного зрения с привязкой
- **LightOnOCR**: Специализированный OCR для игровых журналов
- **Tesseract**: Традиционный движок OCR
- Результат: `work/magazine/ocr_deepseek/`, `ocr_lightonocr/`, `ocr_tesseract/`

### Шаг 3: Объединение и исправление
- Сведение всех результатов OCR с помощью gemma3n
- Исправление ошибок, сохранение структуры, вывод чистого текста
- Результат: `work/magazine/merged/page_XXXX_corrected.txt`

### Шаг 4: Извлечение структуры
- Анализ полного текста журнала с помощью удалённой LLM
- Идентификация статей, назначение категорий, привязка к страницам
- Результат: `work/magazine/structure.json`

### Шаг 5: Форматирование вывода
- Извлечение отдельных статей из объединённых страниц
- Форматирование в чистый Markdown с YAML-метаданными
- Организация в каталоги по категориям
- Результат: `output/Magazine_Name/category/Article_Title.md`

## Переменные окружения

```bash
export OPENAI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
export OPENAI_API_KEY="ваш-api-ключ"
export OPENAI_MODEL="gemini-2.0-flash-exp"
```

## Решение проблем

**Ошибки нехватки памяти**: Уменьшите размер пакета или используйте удалённый API для Шага 5 (`--step5-use-remote`)

**Плохое качество OCR**: Увеличьте DPI (`--dpi 400`), удалите рекламные страницы, убедитесь в хорошем качестве скана

**Повторения модели**: Проверьте размеры выходных файлов — необычно большие файлы, вероятно, содержат повторения. Рекомендуется ручная проверка.

**Ошибки парсинга JSON на Шаге 4**: Проверьте `work/magazine/structure_raw.json` на проблемы с ответом API

## Пример (что в директории вывода)

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

## Лицензия

MIT

## Вклад в проект

Приветствуются issues и pull requests в репозитории проекта.
