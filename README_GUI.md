# ming-drlms GUI (Flet)

## Structure
- gui_poc/ (initial app)
  - app.py
  - ui/ (theme + pages)
  - i18n/ (en.json, zh.json)
  - assets/ (fonts/images/bin)
  - Makefile (modular build; copies C binaries to assets/bin)
- scripts/
  - check_i18n.py
  - gui_selfcheck_headless.sh
- .github/workflows/release_gui.yml

## Develop
```bash
make gui_poc             # build C and copy binaries to assets/bin
python -m pip install flet==0.23.2
flet run gui_poc/app.py  # dev run
```

## Pack (CI example)
```bash
flet pack gui_poc/app.py \
  --add-data "gui_poc/assets=assets" \
  --add-data "gui_poc/i18n=i18n" \
  --add-binary "gui_poc/assets/bin/linux/x86_64/*:assets/bin/linux/x86_64"
```

## System Dependencies
See `gui_poc/docs/DEPENDENCIES.md`.

## i18n Check
```bash
python scripts/check_i18n.py
```

## Headless Self-check (CI)
```bash
bash scripts/gui_selfcheck_headless.sh
```
