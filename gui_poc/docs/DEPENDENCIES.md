# GUI System Dependencies (Linux)

The GUI uses Flet/Flutter runtime which depends on media and desktop stacks.

Recommended packages (Ubuntu/Debian):

```bash
sudo apt-get update
sudo apt-get install -y \
  libmpv1 \
  gstreamer1.0-libav gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-base gstreamer1.0-tools
```

Notes:
- Some desktop warnings (Gdk/Atk) are benign and can be ignored.
- Ensure GPU/driver is properly installed for smooth rendering.
- On headless CI, only the headless self-check runs; GUI is not required.
