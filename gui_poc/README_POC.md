# GUI PoC (Flet) for ming-drlms

## Run (dev)
```bash
python -m pip install flet==0.23.2
python gui_poc/app.py
```

## Build C binaries and copy
```bash
make gui_poc_bins
```

## Pack (draft)
```bash
flet pack gui_poc/app.py --add-data "gui_poc/assets=assets" --add-data "gui_poc/i18n=i18n" --add-binary "gui_poc/assets/bin/linux/x86_64/*:assets/bin/linux/x86_64"
```

## Verify
- Visual page loads with pixel theme; buttons hover/press visible.
- Open Selfcheck tab and run checks: log_agent executes; ldd resolves libipc.so.
