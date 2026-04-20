# foamprofiling

## PyQt profiling tool

`pyqt_profiling_tool.py` is a GUI tool for OpenFOAM case profiling:

- edit profiling settings for current case (`system/controlDict`)
- apply and persist settings snapshots
- scan latest `log*` after run and record profiling-related lines
- visualize settings history in table/chart

### Run

```bash
pip install pyqt5 matplotlib
python pyqt_profiling_tool.py
```

Default case directory is current working directory.

## Docs

- Development design and algorithm principles: `DEVELOPMENT.md`