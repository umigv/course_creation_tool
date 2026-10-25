# Course Creation Tool

A desktop map editor for drawing obstacles and lane lines on a 5 cm grid and
placing course waypoints. Courses are saved as `map.json` and `gps.json` in a
course folder.

## First-time setup

### Prerequisites

- Python 3.10 or newer
- A graphical desktop session
- Tkinter (included with the standard Python installers for macOS and Windows)

On Ubuntu or Debian, install the system prerequisites with:

```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk
```

If Python was installed with Homebrew on macOS, install the matching Tk package
as well. For example, Python 3.14 uses:

```bash
brew install python-tk@3.14
```

From the repository root, create a virtual environment and install Pygame:

```bash
python3 -m venv env
source env/bin/activate
python -m pip install --upgrade pip
python -m pip install pygame
```

On Windows, create and activate the environment with:

```powershell
py -3 -m venv env
env\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install pygame
```

The virtual environment only needs to be created once. For later sessions,
activate it again with `source env/bin/activate` on macOS/Linux or
`env\Scripts\Activate.ps1` in Windows PowerShell.

The Save As, Load, and error dialogs use Tkinter across Linux, macOS, and
Windows. Tkinter runs in a small helper process so it does not conflict with
Pygame's macOS application object. No third-party dialog package is used.

## Run the editor

Activate the virtual environment, then start with a blank map:

```bash
python map_editor.py
```

To open an existing course immediately, pass either its folder or its
`map.json` file:

```bash
python map_editor.py /path/to/course
python map_editor.py /path/to/course/map.json
```

The course folder must already contain `map.json`. If it also contains
`gps.json`, the editor loads its waypoints.

Press `Esc` or close the window to exit. To leave the virtual environment after
closing the editor, run:

```bash
deactivate
```

## Basic controls

Use the buttons in the right panel to switch between obstacle, lane-line, and
waypoint modes. `Tab` cycles through the same three modes.

| Input | Action |
| --- | --- |
| Left mouse drag | Paint obstacles or lane lines |
| Right mouse drag | Erase obstacles or lane lines |
| Left mouse click | Place a waypoint in waypoint mode |
| Shift + left click | Place a no-man's-land waypoint |
| Right mouse click | Remove the nearest waypoint |
| Middle mouse drag or Alt + left drag | Pan the map |
| Mouse wheel | Zoom the map, or scroll the side panel |
| `[` / `]` | Shrink / grow the brush |
| `Ctrl+Z` / `Ctrl+Y` | Undo / redo |
| `S` | Save to the current course folder; prompts for a folder if unsaved |
| `Ctrl+S` | Save As |
| `L` | Load a course folder |
| `R` | Reset the view to the origin |
| `Delete` or `Backspace` | Clear the map |
| `Esc` | Exit |

## Course files

Saving writes two files into the selected course folder:

- `map.json` contains the 5 cm resolution, obstacle cells, and lane-line cells.
- `gps.json` contains the GPS datum and waypoints.

Choose a dedicated folder for each course so these files do not overwrite an
unrelated map.

## Troubleshooting

- **`ModuleNotFoundError: No module named 'pygame'`:** activate the virtual
  environment and run `python -m pip install pygame`.
- **Save As or Load does nothing:** start the editor from a graphical desktop
  session and confirm that Tkinter is available by running
  `python -m tkinter`. On Ubuntu or Debian, install it with
  `sudo apt install python3-tk`.
- **macOS reports that the window was forcibly resized:** update to the latest
  project version. The editor uses SDL's logical Retina coordinates and should
  request a 1340 × 820 point window rather than doubling that size.
- **The window cannot open:** the editor requires a graphical session; it will
  not run in a headless terminal without a display server.
